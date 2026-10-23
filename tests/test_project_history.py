from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import numpy as np

import test_web_studio as studio_fixture
from reconstruction_probe.lod_cache import write_vertex_preview_ply
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PROJECT_ROOTS
from reconstruction_probe.project_history import project_file_lock
from reconstruction_probe.web_studio import Studio,make_handler


class ProjectHistoryTests(unittest.TestCase):
    def setUp(self):
        f=studio_fixture.WebStudioTests();f.setUp();self.addCleanup(f.tearDown);self.f=f;self.root=f.root;self.studio=f.studio
        self.other=f.study/'experiments/history/scan_test/tsdf_pointcloud_mm.ply';self.other.parent.mkdir(parents=True)
        write_vertex_preview_ply(self.other,np.array([[0,0,101],[10,0,101],[0,10,101],[10,10,101]],np.float32),np.full((4,3),120,np.uint8),np.arange(4))
        self.studio.refresh();self.history=self.studio.history
        self.a=next(m for m in self.studio.models.values() if Path(m['path'])==f.model)
        self.b=next(m for m in self.studio.models.values() if Path(m['path'])==self.other)

    def save_request(self,model=None,context=None):
        model=model or self.a;context=context or self.history.context('scan_test')
        return dict(scan_id='scan_test',index_sha256=context['index_sha256'],state_sha256=context['state_sha256'],action='save',
            models=[dict(id=model['id'],sha256=file_sha256(Path(model['path'])))],label='Automated test snapshot',decision='Synthetic API state transition; not manual geometry approval')

    def action(self,action,context=None,**extra):
        c=context or self.history.context('scan_test')
        return self.history.change(dict(scan_id='scan_test',index_sha256=c['index_sha256'],state_sha256=c['state_sha256'],action=action,**extra))

    def state_bytes(self):return (self.history.folder('scan_test')/'state.json').read_bytes()

    def test_read_only_empty_context_then_initial_snapshot_preserves_sources(self):
        self.assertEqual(self.history.context('scan_test')['state_sha256'],'empty');self.assertFalse(self.history.directory.exists())
        before={p:p.read_bytes() for p in [self.f.model,self.other,self.studio.indices['scan_test'][0]]}
        result=self.history.change(self.save_request());self.assertIsNotNone(result['active']);self.assertFalse(result['can_undo'])
        self.assertEqual(result['active_version']['models'][0]['id'],self.a['id'])
        for path,raw in before.items():self.assertEqual(path.read_bytes(),raw)

    def test_save_undo_redo_restore_and_branch_survive_service_restart(self):
        first=self.history.change(self.save_request());v1=first['active'];second=self.history.change(self.save_request(self.b));v2=second['active']
        self.assertEqual(second['active_version']['parent_id'],v1);self.assertTrue(second['can_undo'])
        undone=self.action('undo');self.assertEqual(undone['active'],v1);self.assertTrue(undone['can_redo'])
        restored=Studio(self.root).history.context('scan_test');self.assertEqual(restored['active'],v1);self.assertTrue(restored['can_redo'])
        self.assertEqual(self.action('redo')['active'],v2)
        self.action('restore',version_id=v1);third=self.history.change(self.save_request(self.a));v3=third['active']
        self.assertEqual(third['active_version']['parent_id'],v1);self.assertEqual({v['id'] for v in third['versions']},{v1,v2,v3});self.assertFalse(third['can_redo'])
        self.assertEqual([e['sequence'] for e in third['events']],list(range(1,7)))

    def test_stale_page_and_two_service_instances_cannot_overwrite_history(self):
        request=self.save_request();other=Studio(self.root).history;barrier=threading.Barrier(2)
        def run(service):
            barrier.wait()
            try:return service.change(copy.deepcopy(request))['active']
            except ValueError:return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(run,[self.history,other]))
        self.assertEqual(outcomes.count('rejected'),1);self.assertEqual(len(self.history.context('scan_test')['versions']),1)
        with self.assertRaises(ValueError):self.history.change(request)

    def test_os_lock_is_exclusive_and_released_after_child_exit(self):
        path=self.root/'lock/test.lock'
        code="from pathlib import Path; import sys; from reconstruction_probe.project_history import project_file_lock; ctx=project_file_lock(Path(sys.argv[1])); ctx.__enter__(); print('locked',flush=True); sys.stdin.readline()"
        child=subprocess.Popen([sys.executable,'-c',code,str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'locked')
            with self.assertRaises(ValueError):
                with project_file_lock(path):pass
            child.communicate('exit\n',timeout=10)
            self.assertEqual(child.returncode,0)
            with project_file_lock(path):pass
        finally:
            if child.poll() is None:child.kill();child.communicate()

    def test_invalid_selections_and_unknown_fields_do_not_create_state(self):
        request=self.save_request()
        for patch in [dict(models=[]),dict(models=request['models']*2),dict(models=[dict(id='missing',sha256='0'*64)]),
            dict(models=[dict(id=self.a['id'],sha256='0'*64)]),dict(label=''),dict(decision=''),dict(index_sha256='0'*64),dict(command='not allowed')]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):self.history.change({**request,**patch})
        self.assertFalse((self.history.folder('scan_test')/'state.json').exists())
        original=self.a['scan_id'];self.a['scan_id']='another_scan'
        try:
            with self.assertRaises(ValueError):self.history.change(request)
        finally:self.a['scan_id']=original

    def test_changed_missing_or_recatalogued_target_cannot_be_restored(self):
        one=self.history.change(self.save_request());v1=one['active'];self.history.change(self.save_request(self.b));before=self.state_bytes()
        raw=self.f.model.read_bytes();self.f.model.write_bytes(raw+b'changed')
        try:
            c=self.history.context('scan_test');self.assertTrue(c['undo_blocked']);self.assertFalse(c['can_undo'])
            with self.assertRaises(ValueError):self.action('undo',c)
            self.assertEqual(self.state_bytes(),before)
        finally:self.f.model.write_bytes(raw)
        self.assertEqual(self.action('undo')['active'],v1)
        self.other.unlink();c=self.history.context('scan_test');self.assertTrue(c['redo_blocked'])
        with self.assertRaises(ValueError):self.action('redo',c)

    def test_changed_index_and_corrupt_state_are_visible_without_rewriting_evidence(self):
        c=self.history.change(self.save_request());index=self.studio.indices['scan_test'][0];raw=index.read_bytes();index.write_bytes(raw+b' ')
        context=self.history.context('scan_test');self.assertFalse(context['active_version']['available'])
        with self.assertRaises(ValueError):self.action('restore',context,version_id=c['active'])
        index.write_bytes(raw);path=self.history.folder('scan_test')/'state.json';record=json.loads(path.read_text(encoding='utf-8'));record['active']='missing';path.write_text(json.dumps(record),encoding='utf-8');before=path.read_bytes()
        with self.assertRaises(ValueError):self.history.context('scan_test')
        self.assertEqual(path.read_bytes(),before)

    def test_historical_paths_are_mapped_only_in_memory(self):
        c=self.history.change(self.save_request());path=self.history.folder('scan_test')/'state.json';record=json.loads(path.read_text(encoding='utf-8'))
        def old(p):return PROJECT_ROOTS[0]+chr(92)+str(Path(p).relative_to(self.root)).replace('/',chr(92))
        version=record['versions'][c['active']];version['index_path']=old(version['index_path'])
        for row in version['models']:row['path']=old(row['path'])
        version['input_sha256']={old(p):sha for p,sha in version['input_sha256'].items()}
        path.write_text(json.dumps(record),encoding='utf-8');before=path.read_bytes();context=self.history.context('scan_test')
        self.assertTrue(context['active_version']['available']);self.assertEqual(path.read_bytes(),before)

    def completed_pair(self):
        job_id='1'*16;review_id='2'*16;folder=self.studio.output/job_id;model=folder/'result/nodes/corrected/scan_test/tsdf_pointcloud_mm.ply';model.parent.mkdir(parents=True)
        model.write_bytes(self.other.read_bytes());review=self.studio.fragments.reviews/review_id;review.mkdir(parents=True)
        plan=review/'fragment-plan.json';plan.write_text('{}');(folder/'review-original.json').write_text('{}');(folder/'binding.json').write_text('{}')
        summary=dict(scan_id='scan_test',same_original_frames_and_roi_pixels=True,results=[dict(path=str(model),saved_control=False)],
            reviewed_plan_sha256=file_sha256(plan),selected_frames=2,selected_depth_with_frame_ids_sha256='3'*64)
        (folder/'result/summary.json').write_text(json.dumps(summary))
        state=dict(status='completed',nodes=[dict(id='corrected',tool='fragments.fuse',status='completed',output_sha256={'scan_test/tsdf_pointcloud_mm.ply':file_sha256(model)})])
        (folder/'result/state.json').write_text(json.dumps(state))
        self.studio.jobs[job_id]=dict(id=job_id,kind='fragment_fusion',status='completed',scan_id='scan_test',folder=str(folder),review_id=review_id,
            reviewed_plan_sha256=file_sha256(plan),reviewed_record_sha256=file_sha256(folder/'review-original.json'))
        self.studio.refresh();meta=next(m for m in self.studio.models.values() if m['path']==str(model))
        return folder,model,meta

    def test_completed_fusion_provenance_is_pinned_and_later_change_blocks_restore(self):
        folder,model,meta=self.completed_pair();c=self.history.change(self.save_request(meta));origin=c['active_version']['provenance'][0]
        self.assertEqual(origin['kind'],'completed_fragment_fusion');self.assertFalse(origin['saved_control'])
        self.assertEqual(origin['selected_frames'],2);self.history.change(self.save_request(self.a))
        (folder/'binding.json').write_text('{"changed":true}')
        with self.assertRaises(ValueError):self.action('restore',version_id=c['active'])

    def test_replaced_fusion_model_is_not_rebaselined_as_the_original_job_output(self):
        folder,model,meta=self.completed_pair();model.write_bytes(self.f.model.read_bytes())
        with self.assertRaisesRegex(ValueError,'输出SHA'):self.history.change(self.save_request(meta))
        self.assertFalse((self.history.folder('scan_test')/'state.json').exists())

    def test_pinned_cloud_loading_checks_bytes_even_when_unpinned_preview_was_cached(self):
        sha=file_sha256(self.f.model);self.studio.cloud(self.a['id'],100)
        self.assertEqual(self.studio.cloud(self.a['id'],100,sha)['sourceSha256'],sha)
        raw=self.f.model.read_bytes();self.f.model.write_bytes(raw+b'changed')
        with self.assertRaises(ValueError):self.studio.cloud(self.a['id'],100,sha)

    def test_failed_atomic_replace_preserves_previous_history_and_cleans_temporary(self):
        self.history.change(self.save_request());before=self.state_bytes()
        with patch('reconstruction_probe.project_history.Path.replace',side_effect=OSError('synthetic commit failure')):
            with self.assertRaises(OSError):self.history.change(self.save_request(self.b))
        self.assertEqual(self.state_bytes(),before)
        self.assertFalse(list(self.history.folder('scan_test').glob('*.tmp-*')))
        self.assertEqual(len(Studio(self.root).history.context('scan_test')['versions']),1)

    def test_wrong_cached_hash_and_unpinned_local_region_cannot_replace_version_data(self):
        sha=file_sha256(self.f.model);self.studio.cloud(self.a['id'],100)
        for cloud in self.studio.cache.values():cloud['sourceSha256']='0'*64
        self.assertEqual(self.studio.cloud(self.a['id'],100,sha)['sourceSha256'],sha)
        with self.assertRaisesRegex(ValueError,'版本SHA'):self.studio.region(self.a['id'],0,5.,'0'*64)

    def test_malformed_record_shapes_fail_read_only(self):
        self.history.change(self.save_request());path=self.history.folder('scan_test')/'state.json';record=json.loads(self.state_bytes())
        changes=[[],dict(record,active=None)]
        malformed=copy.deepcopy(record);malformed['versions'][record['active']]['input_sha256']=[];changes.append(malformed)
        for value in changes:
            path.write_text(json.dumps(value),encoding='utf-8');raw=path.read_bytes()
            with self.assertRaises(ValueError):self.history.context('scan_test')
            self.assertEqual(path.read_bytes(),raw)

    def test_cyclic_parent_history_is_not_silently_repaired(self):
        c=self.history.change(self.save_request());path=self.history.folder('scan_test')/'state.json';record=json.loads(self.state_bytes())
        record['versions'][c['active']]['parent_id']=c['active'];path.write_text(json.dumps(record),encoding='utf-8');raw=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'循环'):self.history.context('scan_test')
        self.assertEqual(path.read_bytes(),raw)

    def test_http_context_transition_origin_and_stale_revision(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.studio));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/history?scan=scan_test') as r:self.assertEqual(json.load(r)['state_sha256'],'empty')
            body=json.dumps(self.save_request()).encode()
            with self.assertRaises(HTTPError) as denied:urlopen(Request(base+'/api/history',data=body,headers={'Content-Type':'application/json','Origin':'https://foreign.invalid'}))
            self.assertEqual(denied.exception.code,403);denied.exception.close()
            with urlopen(Request(base+'/api/history',data=body,headers={'Content-Type':'application/json'})) as r:self.assertIsNotNone(json.load(r)['active'])
            with self.assertRaises(HTTPError) as stale:urlopen(Request(base+'/api/history',data=body,headers={'Content-Type':'application/json'}))
            self.assertEqual(stale.exception.code,400);stale.exception.close()
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
