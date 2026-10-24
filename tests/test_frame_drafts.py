from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import copy
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import test_web_fragments as fixture
from reconstruction_probe.frame_drafts import FrameDrafts
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PROJECT_ROOTS


class FrameDraftTests(unittest.TestCase):
    def setUp(self):
        f=fixture.WebFragmentEditorTests();f.setUp();self.addCleanup(f.doCleanups);self.f=f;self.root=f.root;self.studio=f.studio;self.service=self.studio.frame_drafts
        a=f.context['alignments'][0]
        self.draft=dict(format='fragment-editor-draft',format_version=1,unit='mm',alignment=dict(relative_path=a['relative_path'],sha256=a['sha256']),candidate=a['candidates'][0],mode='frame_id',source_frames=str(2**60)+',',target_frames='',source_basis='',target_basis='Unfinished basis',decision='',roi_fields=['-5','','90','30','',''],fusion_fields=dict(voxel_mm='.8',truncation_mm='',edge_threshold_mm='3',weight_threshold='3'))
    def request(self,draft=None,context=None):
        c=context or self.service.context('scan_A')
        return dict(scan_id='scan_A',index_sha256=c['index_sha256'],state_sha256=c['state_sha256'],label='Automated incomplete draft',draft=copy.deepcopy(self.draft if draft is None else draft))
    def path(self):return self.service.folder('scan_A')/'state.json'
    def restore(self,service=None):
        service=service or self.service;c=service.context('scan_A');return service.context('scan_A',c['drafts'][0]['id'],c['index_sha256'])

    def test_partial_large_ids_and_parameters_survive_restart_without_depth_reads(self):
        before={p:p.read_bytes() for p in [self.f.fixture.index,*self.f.fixture.models.values(),self.f.fixture.summary]}
        self.assertEqual(self.service.context('scan_A')['state_sha256'],'empty');self.assertFalse(self.service.directory.exists())
        with patch('numpy.load',side_effect=AssertionError('Draft must not decode raw frames')):
            result=self.service.save(self.request());restored=self.restore(FrameDrafts(self.studio))
        self.assertEqual(restored['draft'],self.draft);self.assertEqual(restored['alignment_id'],self.f.alignment['id'])
        self.assertNotIn('coordinate_confirmed',restored['draft']);self.assertNotIn('review_id',restored['draft']);self.assertEqual(len(self.studio.jobs),1);self.assertFalse(self.studio.fragments.reviews.exists())
        for p,raw in before.items():self.assertEqual(p.read_bytes(),raw)

    def test_draft_without_alignment_and_invalid_form_ideas_remain_nonexecutable(self):
        draft={**self.draft,'alignment':None,'candidate':'','source_frames':'still deciding 1-','roi_fields':['bad','','','','','']}
        self.service.save(self.request(draft));r=self.restore();self.assertEqual(r['draft'],draft);self.assertEqual(r['alignment_id'],'');self.assertEqual(len(r['input_sha256']),1)

    def test_unknown_confirmation_execution_fields_and_malformed_shapes_are_rejected(self):
        for extra in [{'coordinate_confirmed':True},{'review_id':'old'},{'command':'run'}]:
            with self.subTest(extra=extra),self.assertRaises(ValueError):self.service.save(self.request({**self.draft,**extra}))
        cases=[dict(format_version=True),dict(unit='m'),dict(mode='infer'),dict(roi_fields=[0]*6),dict(roi_fields=['']*5),dict(fusion_fields={}),dict(candidate='absent'),dict(alignment={'relative_path':'../outside','sha256':'0'*64}),dict(source_frames='x'*100001)]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ValueError):self.service.save(self.request({**self.draft,**change}))
        self.assertFalse(self.path().exists())

    def test_saved_index_alignment_session_and_source_revisions_block_restore(self):
        self.service.save(self.request());before=self.path().read_bytes()
        for p in [self.f.fixture.index,self.root/self.f.alignment['relative_path'],self.f.fixture.models['source'],self.f.studio.output/'1111111111111111/result/session-original.json']:
            raw=p.read_bytes();p.write_bytes(raw+b' ')
            try:
                c=self.service.context('scan_A');self.assertFalse(c['drafts'][0]['available'])
                with self.assertRaises(ValueError):self.service.context('scan_A',c['drafts'][0]['id'],c['index_sha256'])
            finally:p.write_bytes(raw)
        self.assertEqual(before,self.path().read_bytes())

    def test_two_service_writers_stale_cas_and_atomic_write_failure(self):
        req=self.request();barrier=threading.Barrier(2)
        def run(service):
            barrier.wait()
            try:return service.save(copy.deepcopy(req))['saved_id']
            except ValueError:return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[self.service,FrameDrafts(self.studio)]))
        self.assertEqual(results.count('blocked'),1);self.assertEqual(len(self.service.context('scan_A')['drafts']),1)
        with self.assertRaises(ValueError):self.service.save(req)
        before=self.path().read_bytes()
        with patch('reconstruction_probe.project_history.os.replace',side_effect=OSError('injected interrupted write')):
            with self.assertRaises(OSError):self.service.save(self.request())
        self.assertEqual(before,self.path().read_bytes());self.assertFalse(list(self.path().parent.glob('*.tmp-*')))

    def test_corrupt_state_preserves_bytes_instead_of_resetting(self):
        self.service.save(self.request());record=json.loads(self.path().read_text(encoding='utf-8'));record['drafts'][0]['draft']['review_id']='not allowed';self.path().write_text(json.dumps(record),encoding='utf-8');before=self.path().read_bytes()
        with self.assertRaises(ValueError):self.service.context('scan_A')
        self.assertEqual(before,self.path().read_bytes())

    def test_historical_paths_map_in_memory_and_alignment_identity_is_relative(self):
        self.service.save(self.request());record=json.loads(self.path().read_text(encoding='utf-8'))
        record['drafts'][0]['input_sha256']={str(PROJECT_ROOTS[0]).rstrip(chr(92))+chr(92)+str(Path(k).relative_to(self.root)):v for k,v in record['drafts'][0]['input_sha256'].items()}
        self.path().write_text(json.dumps(record),encoding='utf-8');before=self.path().read_bytes();self.assertEqual(self.restore()['draft'],self.draft);self.assertEqual(before,self.path().read_bytes())

    def test_portable_inspection_never_saves_or_creates_review(self):
        r=self.service.inspect(dict(scan_id='scan_A',index_sha256=self.f.context['index_sha256'],draft=self.draft));self.assertEqual(r['draft'],self.draft);self.assertTrue(r['requires_review']);self.assertFalse(self.service.directory.exists());self.assertFalse(self.studio.fragments.reviews.exists())
        with self.assertRaises(ValueError):self.service.inspect(dict(scan_id='scan_A',index_sha256='0'*64,draft=self.draft))

    def test_http_context_save_restore_inspect_and_foreign_origin(self):
        from reconstruction_probe.web_studio import make_handler
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.studio));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/frame-drafts?scan=scan_A') as r:self.assertEqual(json.load(r)['state_sha256'],'empty')
            body=json.dumps(self.request()).encode()
            with self.assertRaises(HTTPError) as e:urlopen(Request(base+'/api/frame-drafts',data=body,headers={'Origin':'https://foreign.invalid'}))
            self.assertEqual(e.exception.code,403);e.exception.close()
            with urlopen(Request(base+'/api/frame-drafts',data=body,headers={'Content-Type':'application/json'})) as r:self.assertEqual(r.status,201);saved=json.load(r)
            with urlopen(base+'/api/frame-drafts?scan=scan_A&draft_id='+saved['saved_id']+'&index_sha256='+saved['index_sha256']) as r:self.assertEqual(json.load(r)['draft'],self.draft)
            request=dict(scan_id='scan_A',index_sha256=saved['index_sha256'],draft=self.draft)
            with urlopen(Request(base+'/api/frame-drafts/inspect',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'})) as r:self.assertEqual(json.load(r)['draft'],self.draft)
            self.assertEqual(len(self.service.context('scan_A')['drafts']),1)
        finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
