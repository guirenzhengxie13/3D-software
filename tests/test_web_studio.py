import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest
import shutil
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import numpy as np

from reconstruction_probe.lod_cache import write_vertex_preview_ply
from reconstruction_probe.web_studio import Studio,make_handler


class WebStudioTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.study=self.root/'reports/range2-study-20261018';scan=self.study/'decoded/scan_test';frame=scan/'frame_0000000000';frame.mkdir(parents=True)
        self.source=self.root/'inputs';self.source.mkdir();self.model=self.study/'reconstruction/scan_test/tsdf_pointcloud_mm.ply';self.model.parent.mkdir(parents=True)
        xyz=np.array([[0,0,100],[10,0,100],[0,10,100],[10,10,100]],np.float32);write_vertex_preview_ply(self.model,xyz,np.full((4,3),100,np.uint8),np.arange(4))
        self.index=dict(scan_id='scan_test',source_directory=str(self.source),optical_to_pose_axes=[1,1,1],
            intrinsics=dict(Pl=dict(width=2,height=2,K=[[1,0,0],[0,1,0],[0,0,1]])),
            status=dict(valid_depth_points=3,poses_parsed=1),frames=[dict(id=0,points=3)])
        (scan/'index.json').write_text(json.dumps(self.index),encoding='utf-8')
        np.savez_compressed(frame/'frame.npz',depth_mm=np.array([[100,0],[100,100]],np.float32),rgba=np.array([[10,20,30,255],[40,50,60,255],[70,80,90,255]],np.uint8))
        pose=np.eye(4);pose[0,3]=12;np.save(frame/'pose_stored.npy',pose)
        (self.root/'web/studio').mkdir(parents=True);(self.root/'web/studio/index.html').write_text('<h1>studio</h1>',encoding='utf-8');(self.root/'secret.txt').write_text('not served')
        self.studio=Studio(self.root)

    def tearDown(self):self.temp.cleanup()

    def test_catalog_preview_and_stored_pose_reprojection_preserve_identity(self):
        self.assertEqual(self.studio.catalog['summary']['observations'],3);meta=next(iter(self.studio.models.values()));cloud=self.studio.cloud(meta['id'],100)
        self.assertEqual(cloud['originalPoints'],4);self.assertEqual(cloud['displayPoints'],4)
        np.testing.assert_array_equal(np.frombuffer(base64.b64decode(cloud['ids']),'<u4'),[0,1,2,3])
        f=self.studio.frame('scan_test',0);self.assertTrue(f['pose_available'])
        np.testing.assert_array_equal(np.frombuffer(base64.b64decode(f['xyz']),'<f4').reshape(-1,3),[[12,0,100],[12,100,100],[112,100,100]])
        np.testing.assert_array_equal(np.frombuffer(base64.b64decode(f['ids']),'<u4'),[0,2,3])
        self.assertTrue(self.studio.depth_image('scan_test',0).startswith(b'\x89PNG'))

    def test_http_catalog_and_boundary_checks(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.studio));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(url+'/api/catalog') as response:self.assertEqual(json.load(response)['summary']['projects'],1)
            with urlopen(url+'/') as response:self.assertIn(b'<h1>studio',response.read())
            for path in ['/secret.txt','/web/%2e%2e/%2e%2e/secret.txt','/api/cloud?id=absent']:
                with self.assertRaises(HTTPError):urlopen(url+path)
            request=Request(url+'/api/jobs',data=b'{}',headers={'Origin':'https://unrelated.invalid','Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as failure:urlopen(request)
            self.assertEqual(failure.exception.code,403)
            with self.assertRaises(HTTPError):urlopen(Request(url+'/',headers={'Host':'unrelated.invalid'}))
        finally:server.shutdown();server.server_close();worker.join()

    def test_unknown_model_job_and_foreign_session_cannot_create_outputs(self):
        with self.assertRaises(ValueError):self.studio.start_job(dict(kind='spatial',model_id='missing'))
        with self.assertRaises(ValueError):self.studio.start_job(dict(kind='alignment',session=dict(source=dict(path=str(self.root/'secret.txt')),target=dict(path=str(self.model)))))
        self.assertFalse(self.studio.output.exists())

    def test_refresh_does_not_publish_an_empty_model_catalog_between_steps(self):
        from reconstruction_probe.ply_layout import inspect_ply
        entered=threading.Event();resume=threading.Event();old_id=next(iter(self.studio.models));errors=[]
        def slow(path):
            entered.set()
            if not resume.wait(5):raise RuntimeError('test refresh synchronization timed out')
            return inspect_ply(path)
        def refresh():
            try:self.studio.refresh()
            except Exception as error:errors.append(error)
        with patch('reconstruction_probe.web_studio.inspect_ply',side_effect=slow):
            worker=threading.Thread(target=refresh);worker.start()
            try:
                self.assertTrue(entered.wait(5));self.assertIn(old_id,self.studio.models)
                self.assertEqual(self.studio.catalog['summary']['models'],1)
            finally:resume.set();worker.join(5)
        self.assertFalse(errors);self.assertIn(old_id,self.studio.models)

    def test_workbench_reference_preserves_official_model_role_and_name(self):
        official=self.source/'pointclouds/Fused renamed (0.40mm).ply';official.parent.mkdir();shutil.copyfile(self.model,official)
        report=self.study/'official-fusion-comparison/summary.json';report.parent.mkdir()
        report.write_text(json.dumps(dict(pairs=[dict(scan_id='scan_test',metadata=dict(referenceKind='saved-fusion'),source_sha256={str(official):'pinned-by-comparison'})])),encoding='utf-8')
        page=self.study/'experiments/pair/workbench.html';page.parent.mkdir(parents=True)
        payload=dict(clouds=[dict(path=str(official),originalPoints=4,label='fixed'),dict(path=str(self.model),originalPoints=4,label='moving')])
        page.write_text('<script id="alignment-data" type="application/json">'+json.dumps(payload)+'</script>',encoding='utf-8');self.studio.refresh()
        item=next(m for m in self.studio.models.values() if m['path']==str(official.resolve()))
        self.assertEqual(item['role'],'official');self.assertEqual(item['label'],'官方保存融合')


if __name__=='__main__':unittest.main()
