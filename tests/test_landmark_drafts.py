from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import base64
import copy
import json
from pathlib import Path
import shutil
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import numpy as np

import test_web_studio as fixture
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.project_history import project_file_lock
from reconstruction_probe.path_mapping import PROJECT_ROOTS
from reconstruction_probe.web_studio import Studio,make_handler


class LandmarkDraftTests(unittest.TestCase):
    def setUp(self):
        f=fixture.WebStudioTests();f.setUp();self.addCleanup(f.tearDown);self.root=f.root;self.f=f
        self.folder=f.study/'experiments/draft-fixture';self.folder.mkdir(parents=True)
        self.source=self.folder/'source.ply';shutil.copyfile(f.model,self.source)
        self.candidate=self.folder/'candidates.json';self.candidate.write_text('{"candidates": []}',encoding='utf-8')
        self.xyz=np.array([[0,0,100],[10,0,100],[0,10,100],[10,10,100]],'<f4')
        def cloud(path,index):return dict(path=str(path),sourceSha256=file_sha256(path),originalPoints=4,displayPoints=4,fragmentId=index,label=str(index),xyz=base64.b64encode(self.xyz.tobytes()).decode(),ids=base64.b64encode(np.arange(4,dtype='<u4').tobytes()).decode(),rgb=base64.b64encode(bytes([120]*12)).decode())
        self.data=dict(formatVersion=1,unit='mm',clouds=[cloud(f.model,0),cloud(self.source,1)],candidates=[dict(label='identity',transform=np.eye(4).tolist())],candidateReference=dict(path=str(self.candidate),sha256=file_sha256(self.candidate)))
        self.page=self.folder/'workbench.html';self.page.write_text('<html><script id="alignment-data" type="application/json">'+json.dumps(self.data)+'</script><p>historical presentation</p></html>',encoding='utf-8')
        self.studio=Studio(self.root);self.service=self.studio.landmark_drafts;self.identifier=next(iter(self.studio.pages))
        self.draft=dict(format='reconstruction-landmark-draft',format_version=1,unit='mm',target=dict(sha256=self.data['clouds'][0]['sourceSha256'],fragment_id=0),source=dict(sha256=self.data['clouds'][1]['sourceSha256'],fragment_id=1),candidate_label='identity',candidate_sha256=file_sha256(self.candidate),requires_recompute=True,point_pairs=[],pending_target=None)

    def selected(self,index):return dict(id=index,xyz=self.xyz[index].astype(float).tolist())
    def pairs(self,count=2):return [dict(target=self.selected(i),source=self.selected(i)) for i in range(count)]
    def request(self,draft=None,context=None):
        c=context or self.service.context(self.identifier)
        return dict(workbench_id=self.identifier,page_sha256=c['page_sha256'],state_sha256=c['state_sha256'],label='Automated incomplete draft',draft=copy.deepcopy(self.draft if draft is None else draft))
    def state_path(self):return self.service.folder(self.page.relative_to(self.root).as_posix())/'state.json'
    def restore(self,service=None,identifier=None):
        service=service or self.service;identifier=identifier or self.identifier;c=service.context(identifier)
        return service.context(identifier,c['drafts'][0]['id'],c['page_sha256'])['draft']

    def test_partial_pending_and_empty_snapshots_survive_restart_without_processing(self):
        originals={p:p.read_bytes() for p in [self.page,self.source,self.f.model,self.candidate]}
        c=self.service.context(self.identifier);self.assertEqual(c['state_sha256'],'empty');self.assertFalse(self.service.directory.exists())
        self.service.save(self.request());self.draft['point_pairs']=self.pairs(1);self.draft['pending_target']=self.selected(2)
        second=self.service.save(self.request());self.assertEqual(len(second['drafts']),2)
        self.assertEqual(self.restore(),self.draft)
        self.assertEqual(self.restore(Studio(self.root).landmark_drafts),self.draft)
        self.assertFalse(self.studio.jobs);self.assertFalse(self.studio.output.exists())
        for path,raw in originals.items():self.assertEqual(path.read_bytes(),raw)

    def test_unfit_or_collinear_draft_is_preserved_but_never_fitted(self):
        self.draft['point_pairs']=self.pairs(3)
        # Deliberately wrong physical matches are legal draft ideas, not approved geometry.
        self.draft['point_pairs'][1]['source']=self.selected(3)
        self.service.save(self.request());self.assertEqual(self.restore(),self.draft)
        self.assertNotIn('transform_source_to_target',self.restore());self.assertFalse(self.studio.jobs)

    def test_malformed_foreign_duplicate_and_changed_coordinates_are_rejected(self):
        self.draft['point_pairs']=self.pairs(2)
        cases=[]
        def case(change):
            row=copy.deepcopy(self.draft);change(row);cases.append(row)
        case(lambda r:r.update(command='execute'))
        case(lambda r:r.update(format_version=True))
        case(lambda r:r.update(requires_recompute=1))
        case(lambda r:r['source'].update(fragment_id=True))
        case(lambda r:r['source'].update(sha256='0'*64))
        case(lambda r:r.update(candidate_label='foreign'))
        case(lambda r:r.update(candidate_sha256='0'*64))
        case(lambda r:r['point_pairs'].append(copy.deepcopy(r['point_pairs'][0])))
        case(lambda r:r['point_pairs'][0]['source'].update(id=99))
        case(lambda r:r['point_pairs'][0]['source'].update(id=True))
        case(lambda r:r['point_pairs'][0]['source'].update(xyz=[1,2,3]))
        case(lambda r:r['point_pairs'][0]['source'].update(xyz=[float('nan'),0,100]))
        case(lambda r:r.update(point_pairs=r['point_pairs']*33))
        case(lambda r:r.update(pending_target=dict(id=99,xyz=[0,0,0])))
        for row in cases:
            with self.subTest(row=row),self.assertRaises((ValueError,TypeError)):self.service.save(self.request(row))
        self.assertFalse(self.state_path().exists())

    def test_pending_target_may_repeat_existing_target_without_forming_duplicate_pair(self):
        self.draft['point_pairs']=self.pairs(1);self.draft['pending_target']=self.selected(0)
        self.service.save(self.request());self.assertEqual(self.restore(),self.draft)

    def test_page_and_actual_model_and_candidate_change_block_stale_restoration(self):
        c=self.service.save(self.request());raw=self.state_path().read_bytes();page=self.page.read_bytes()
        self.page.write_bytes(page+b' changed presentation')
        changed=self.service.context(self.identifier);self.assertFalse(changed['drafts'][0]['available'])
        with self.assertRaises(ValueError):self.service.context(self.identifier,c['saved_id'],c['page_sha256'])
        self.page.write_bytes(page)
        for path in [self.source,self.candidate]:
            original=path.read_bytes();path.write_bytes(original+b' ')
            with self.subTest(path=path),self.assertRaises(ValueError):self.service.context(self.identifier)
            path.write_bytes(original)
        self.assertEqual(raw,self.state_path().read_bytes())

    def test_forged_preview_coordinates_cannot_replace_original_vertices(self):
        self.data['clouds'][1]['xyz']=base64.b64encode((self.xyz+1).tobytes()).decode();self.page.write_text('<script id="alignment-data" type="application/json">'+json.dumps(self.data)+'</script>',encoding='utf-8')
        self.draft['point_pairs']=self.pairs(1);self.draft['point_pairs'][0]['source']['xyz']=[1.,1.,101.]
        with self.assertRaises(ValueError):self.service.save(self.request())
        self.assertFalse(self.state_path().exists())

    def test_two_service_writers_and_os_lock_do_not_overwrite_saved_draft(self):
        request=self.request();other=Studio(self.root).landmark_drafts;barrier=threading.Barrier(2)
        def run(service):
            barrier.wait()
            try:return service.save(copy.deepcopy(request))['saved_id']
            except ValueError:return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[self.service,other]))
        self.assertEqual(results.count('blocked'),1);self.assertEqual(len(self.service.context(self.identifier)['drafts']),1)
        with project_file_lock(self.state_path().with_name('writer.lock')):
            with self.assertRaises(ValueError):other.save(self.request())
        with self.assertRaises(ValueError):self.service.save(request)

    def test_atomic_failure_and_corrupted_history_preserve_previous_bytes(self):
        self.service.save(self.request());before=self.state_path().read_bytes()
        with patch('reconstruction_probe.project_history.os.replace',side_effect=OSError('injected replace failure')):
            with self.assertRaises(OSError):self.service.save(self.request())
        self.assertEqual(self.state_path().read_bytes(),before);self.assertFalse(list(self.state_path().parent.glob('*.tmp-*')))
        record=json.loads(before);record['drafts'].append(record['drafts'][0]);self.state_path().write_text(json.dumps(record),encoding='utf-8');corrupt=self.state_path().read_bytes()
        with self.assertRaises(ValueError):self.service.context(self.identifier)
        self.assertEqual(self.state_path().read_bytes(),corrupt)

    def test_in_memory_editor_upgrade_preserves_historical_page_and_embedded_ids(self):
        assets=Path(__file__).resolve().parents[1]/'web/landmark-workbench';shutil.copytree(assets,self.root/'web/landmark-workbench')
        before=self.page.read_bytes();served=self.studio.static_bytes(self.page).decode('utf-8');data=self.studio.workbench_data(served)
        self.assertIn('id="saveDraft"',served);self.assertNotIn('historical presentation',served)
        self.assertEqual(data['serverContext'],dict(workbench_id=self.identifier,page_sha256=file_sha256(self.page)))
        for old,new in zip(self.data['clouds'],data['clouds']):self.assertEqual(old,new)
        self.assertEqual(before,self.page.read_bytes());self.assertNotIn('__APP__',served)

    def test_migrated_saved_pins_are_mapped_in_memory_without_rewriting_state(self):
        self.draft['point_pairs']=self.pairs(1);self.service.save(self.request())
        record=json.loads(self.state_path().read_text(encoding='utf-8'));row=record['drafts'][0]
        row['input_sha256']={str(PROJECT_ROOTS[0]).rstrip(chr(92))+chr(92)+str(Path(k).relative_to(self.root)).replace('/',chr(92)):v for k,v in row['input_sha256'].items()}
        self.state_path().write_text(json.dumps(record),encoding='utf-8');before=self.state_path().read_bytes()
        self.assertEqual(self.restore(),self.draft);self.assertEqual(self.state_path().read_bytes(),before)

    def test_http_save_read_and_foreign_origin_rejection(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.studio));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/landmark-drafts?workbench='+self.identifier) as r:self.assertEqual(json.load(r)['state_sha256'],'empty')
            request=self.request();body=json.dumps(request).encode();endpoint=base+'/api/landmark-drafts'
            with urlopen(Request(endpoint,data=body,headers={'Content-Type':'application/json'})) as r:self.assertEqual(r.status,201);saved=json.load(r)
            with urlopen(base+'/api/landmark-drafts?workbench='+self.identifier+'&draft_id='+saved['saved_id']+'&page_sha256='+saved['page_sha256']) as r:self.assertEqual(json.load(r)['draft'],self.draft)
            with self.assertRaises(HTTPError) as error:urlopen(Request(endpoint,data=body,headers={'Origin':'https://foreign.invalid'}))
            self.assertEqual(error.exception.code,403)
            with self.assertRaises(HTTPError):urlopen(Request(endpoint,data=body))
            self.assertEqual(len(self.service.context(self.identifier)['drafts']),1)
        finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
