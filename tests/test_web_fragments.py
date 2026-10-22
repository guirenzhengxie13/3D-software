import copy
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.web_fragments import frame_selection
from reconstruction_probe.web_studio import Studio,make_handler
import test_fragment_bridge as bridge_fixture


class WebFragmentEditorTests(unittest.TestCase):
    def setUp(self):
        fixture=bridge_fixture.FragmentBridgeTests('test_original_ids_pose_composition_roi_and_content_pins_survive_bridge')
        fixture.setUp();self.addCleanup(fixture.doCleanups);self.fixture=fixture;self.root=fixture.root
        self.studio=Studio(self.root)
        self.studio.indices={'scan_A':(fixture.index,json.loads(fixture.index.read_text(encoding='utf-8')))}
        self.studio.models={side:dict(id=side,path=str(path),scan_id='scan_A',label=side,points=4,unit='mm') for side,path in fixture.models.items()}
        folder=self.studio.output/'1111111111111111';folder.mkdir(parents=True)
        shutil.copytree(fixture.alignment,folder/'result')
        self.studio.jobs={'1111111111111111':dict(id='1111111111111111',kind='alignment',status='completed',folder=str(folder))}
        self.context=self.studio.fragments.context('scan_A');self.alignment=self.context['alignments'][0]
        self.request=dict(scan_id='scan_A',index_sha256=self.context['index_sha256'],alignment_id=self.alignment['id'],
            alignment_sha256=self.alignment['sha256'],candidate='selected_frozen-geometric',mode='ordinal_1based',
            target_frames='1',source_frames='3',target_basis='Explicit target fixture in saved mm coordinates',
            source_basis='Explicit source fixture in saved mm coordinates',decision='Scripted Web API contract test, not human correspondence selection',
            coordinate_confirmed=True,roi=[[-5,-5,90],[30,30,110]])

    def start_request(self,review):
        return dict(kind='fragment_fusion',review_id=review['id'],plan_sha256=review['plan_sha256'],review_sha256=review['review_sha256'])

    def test_context_preserves_nonconsecutive_ids_and_separates_file_presence_from_validation(self):
        self.assertEqual([f['frame_id'] for f in self.context['frames']],['0','8',str(2**40)])
        self.assertEqual([f['ordinal'] for f in self.context['frames']],[1,2,3])
        self.assertTrue(self.context['frames'][2]['optimized_pose_present'])
        self.assertIn('presence',self.context['availability'])
        self.assertEqual(self.alignment['source']['sha256'],file_sha256(self.fixture.models['source']))

    def test_explicit_review_pins_payloads_and_does_not_start_a_job(self):
        before={p:p.read_bytes() for p in [self.fixture.index,self.fixture.models['source'],self.fixture.models['target']]}
        review=self.studio.fragments.preview(self.request)
        self.assertEqual(review['target_frame_ids'],['0']);self.assertEqual(review['source_frame_ids'],[str(2**40)])
        self.assertEqual(review['summary']['selected_frames'],2);self.assertEqual(len(self.studio.jobs),1)
        folder=self.studio.fragments.reviews/review['id']
        self.assertEqual(review['review_sha256'],file_sha256(folder/'review.json'))
        plan=json.loads((folder/'fragment-plan.json').read_text(encoding='utf-8'))
        self.assertIn(str(self.fixture.decoded/f'frame_{2**40:010d}/frame.npz'),plan['input_sha256'])
        for p,data in before.items():self.assertEqual(p.read_bytes(),data)

    def test_duplicate_unknown_frame_wrong_units_stale_index_and_missing_confirmation_fail(self):
        mutations=[dict(source_frames='1'),dict(source_frames='4'),dict(source_frames='2-1'),
            dict(mode='guess_from_ply'),dict(index_sha256='0'*64),dict(alignment_sha256='0'*64),
            dict(candidate='unknown'),dict(coordinate_confirmed=False),dict(decision=''),dict(command='do not run')]
        for values in mutations:
            with self.subTest(values=values),self.assertRaises(ValueError):self.studio.fragments.preview({**self.request,**values})
        self.assertFalse(self.studio.fragments.reviews.exists(),'cheap invalid forms create no review artifacts')

    def test_missing_optimized_pose_and_corrupt_depth_are_rejected_without_leaking_processing_lock(self):
        frame=self.fixture.decoded/f'frame_{2**40:010d}'
        pose=frame/'pose_optimized.npy';original=pose.read_bytes();pose.unlink()
        with self.assertRaises(ValueError):self.studio.fragments.preview(self.request)
        self.assertTrue(self.studio.processing.acquire(blocking=False));self.studio.processing.release()
        pose.write_bytes(original);depth=frame/'frame.npz';depth.write_bytes(b'PK'+b'bad zip')
        with self.assertRaises(ValueError):self.studio.fragments.preview(self.request)
        records=[json.loads(p.read_text(encoding='utf-8')) for p in self.studio.fragments.reviews.glob('*/review.json')]
        self.assertEqual([r['status'] for r in records],['rejected','rejected'])

    def test_submit_uses_reviewed_revision_and_persists_queued_job_before_execution(self):
        review=self.studio.fragments.preview(self.request)
        with patch('reconstruction_probe.web_studio.threading',SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:None))):
            job=self.studio.start_job(self.start_request(review))
        stored=json.loads((Path(job['folder'])/'job.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['status'],'queued');self.assertEqual(stored['reviewed_record_sha256'],review['review_sha256'])
        self.assertIn('run_fragment_fusion_pair.py',' '.join(job['command_argv']))
        restarted=Studio(self.root);self.assertEqual(restarted.jobs[job['id']]['status'],'interrupted')
        self.assertEqual(json.loads((Path(job['folder'])/'job.json').read_text(encoding='utf-8'))['status'],'queued')
        record=json.loads((self.studio.fragments.reviews/review['id']/'review.json').read_text(encoding='utf-8'))
        self.assertEqual(record['status'],'submitted');self.assertEqual(record['job_id'],job['id'])
        self.studio.jobs[job['id']]['status']='failed'
        with self.assertRaises(ValueError):self.studio.start_job(self.start_request(review))

    def test_modified_plan_record_index_or_payload_cannot_be_executed(self):
        for kind in ['plan','record','index','payload']:
            with self.subTest(kind=kind):
                review=self.studio.fragments.preview(self.request);folder=self.studio.fragments.reviews/review['id']
                path={'plan':folder/'fragment-plan.json','record':folder/'review.json','index':self.fixture.index,
                    'payload':self.fixture.decoded/f'frame_{2**40:010d}/frame.npz'}[kind]
                original=path.read_bytes();path.write_bytes(original+b' ')
                try:
                    with self.assertRaises(ValueError):self.studio.start_job(self.start_request(review))
                finally:path.write_bytes(original)
        self.assertEqual(len(self.studio.jobs),1)

    def test_historical_review_directory_is_resolved_without_rewriting_ready_record(self):
        from reconstruction_probe.path_mapping import PROJECT_ROOTS
        review=self.studio.fragments.preview(self.request);path=self.studio.fragments.reviews/review['id']/'review.json'
        record=json.loads(path.read_text(encoding='utf-8'));record['decoded']=PROJECT_ROOTS[0]+r'\decoded'
        path.write_text(json.dumps(record),encoding='utf-8');before=path.read_bytes()
        folder,loaded,raw=self.studio.fragments.load_review(review['id'],review['plan_sha256'],file_sha256(path))
        self.assertEqual(loaded['decoded'],record['decoded']);self.assertEqual(raw,before);self.assertEqual(path.read_bytes(),before)

    def test_recorded_binding_is_loaded_explicitly_and_edits_cannot_keep_its_provenance(self):
        review=self.studio.fragments.preview(self.request);context=self.studio.fragments.context('scan_A')
        preset=context['presets'][0]
        self.assertEqual(preset['source_text'],str(2**40));self.assertEqual(preset['target_text'],'0')
        request={**self.request,'preset_id':preset['id'],'preset_sha256':preset['sha256']}
        self.assertEqual(self.studio.fragments.preview(request)['summary']['selected_frames'],2)
        with self.assertRaises(ValueError):self.studio.fragments.preview({**request,'source_frames':'2'})

    def test_simultaneous_job_requests_reserve_only_one_worker(self):
        reviews=[self.studio.fragments.preview(self.request) for _ in range(2)]
        fake=SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:None))
        def submit(review):
            try:return self.studio.start_job(self.start_request(review))['status']
            except ValueError:return 'rejected'
        with patch('reconstruction_probe.web_studio.threading',fake):
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(submit,reviews))
        self.assertEqual(sorted(statuses),['queued','rejected'])

    def test_http_review_execution_can_request_between_step_cancellation(self):
        review=self.studio.fragments.preview(self.request)
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.studio))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            fake=SimpleNamespace(Thread=lambda **kwargs:SimpleNamespace(start=lambda:None))
            with patch('reconstruction_probe.web_studio.threading',fake):
                with urlopen(Request(base+'/api/jobs',data=json.dumps(self.start_request(review)).encode(),headers={'Content-Type':'application/json'})) as response:
                    self.assertEqual(response.status,202);job=json.load(response)
            with urlopen(Request(base+'/api/jobs/'+job['id']+'/cancel',data=b'{}',headers={'Content-Type':'application/json'})) as response:
                self.assertEqual(response.status,200)
            self.assertTrue((Path(job['folder'])/'cancel').is_file())
        finally:server.shutdown();server.server_close();thread.join()

    def test_http_context_review_and_foreign_origin(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.studio))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(base+'/api/fragments/context?scan=scan_A') as r:context=json.load(r)
            self.assertEqual(context['frames'][2]['frame_id'],str(2**40))
            body=json.dumps(self.request).encode()
            with self.assertRaises(HTTPError) as denied:urlopen(Request(base+'/api/fragments/reviews',data=body,headers={'Content-Type':'application/json','Origin':'https://foreign.invalid'}))
            self.assertEqual(denied.exception.code,403);denied.exception.close()
            self.assertFalse(self.studio.fragments.reviews.exists())
            with urlopen(Request(base+'/api/fragments/reviews',data=body,headers={'Content-Type':'application/json'})) as r:
                self.assertEqual(r.status,201);review=json.load(r)
            bad=self.start_request(review);bad['plan_sha256']='0'*64
            with self.assertRaises(HTTPError) as stale:urlopen(Request(base+'/api/jobs',data=json.dumps(bad).encode(),headers={'Content-Type':'application/json'}))
            self.assertEqual(stale.exception.code,400);stale.exception.close()
        finally:server.shutdown();server.server_close();thread.join()


class FrameExpressionTests(unittest.TestCase):
    def test_ids_ordinals_and_extreme_ranges(self):
        ids=[0,8,2**60]
        self.assertEqual(frame_selection('1 - 2,3','ordinal_1based',ids),ids)
        self.assertEqual(frame_selection('0，'+str(2**60),'frame_id',ids),[0,2**60])
        for text,mode in [('0','ordinal_1based'),('0-10000000000000000000','frame_id'),('1,1','ordinal_1based'),('-1','frame_id'),('1.2','frame_id')]:
            with self.subTest(text=text),self.assertRaises(ValueError):frame_selection(text,mode,ids)


if __name__=='__main__':unittest.main()
