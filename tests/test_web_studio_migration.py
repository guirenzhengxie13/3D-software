import base64
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

import numpy as np

from reconstruction_probe.lod_cache import write_vertex_preview_ply
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import CAPTURE_ROOT, PROJECT_ROOTS
from reconstruction_probe.web_studio import Studio, make_handler


class StudioMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.study=self.root/'reports/range2-study-20261018'
        self.decoded=self.study/'decoded/scan_test';self.decoded.mkdir(parents=True)
        self.model=self.study/'reconstruction/scan_test/tsdf_pointcloud_mm.ply';self.model.parent.mkdir(parents=True)
        self.xyz=np.array([[0,0,100],[10,0,100],[0,10,100],[10,10,100]],np.float32)
        self.rgb=np.array([[20,40,60],[60,80,100],[100,120,140],[140,160,180]],np.uint8)
        write_vertex_preview_ply(self.model,self.xyz,self.rgb,np.arange(4))
        self.capture=self.root/'data/revo-scan-projects/uuid';(self.capture/'pointclouds').mkdir(parents=True)
        self.official=self.capture/'pointclouds/fuse.ply';shutil.copyfile(self.model,self.official)
        index=dict(scan_id='scan_test',source_directory=CAPTURE_ROOT+r'\uuid',
                   status=dict(valid_depth_points=4),frames=[dict(id=0),dict(id=2)])
        self.index=self.decoded/'index.json';self.index.write_text(json.dumps(index),encoding='utf-8')
        self.frame=self.decoded/'frame_0000000000';self.frame.mkdir()
        np.savez_compressed(self.frame/'frame.npz',depth_mm=np.ones((2,2)))

    def tearDown(self):self.temp.cleanup()

    def old(self,path):return PROJECT_ROOTS[0]+'\\'+str(path.relative_to(self.root)).replace('/','\\')

    def test_official_model_and_old_job_restore_without_rewriting_evidence(self):
        folder=self.root/'reports/web-studio/runs/abc123';folder.mkdir(parents=True)
        job=folder/'job.json';job.write_text(json.dumps(dict(id='abc123',folder=self.old(folder),kind='spatial',status='completed')),encoding='utf-8')
        before={p:p.read_bytes() for p in [self.index,job]}
        studio=Studio(self.root)
        official=next(row for row in studio.models.values() if row['role']=='official')
        self.assertEqual(official['path'],str(self.official));self.assertTrue(official['has_rgb'])
        self.assertEqual(official['color_kind'],'colored')
        self.assertEqual(studio.job('abc123')['folder'],str(folder))
        project=studio.catalog['projects'][0]
        self.assertEqual(project['present_frames'],1);self.assertEqual(project['ready_frame_ordinals'],[0])
        for path,content in before.items():self.assertEqual(path.read_bytes(),content)

    def test_old_lod_metadata_is_used_while_its_bytes_and_hash_remain_unchanged(self):
        folder=self.root/'reports/pointcloud-scale-20261019/lod/cache';folder.mkdir(parents=True)
        np.savez_compressed(folder/'preview-data.npz',original_vertex_ids=np.arange(4,dtype=np.uint64),xyz_mm=self.xyz,rgb=self.rgb)
        manifest=folder/'summary.json';manifest.write_text(json.dumps(dict(format_version=1,unit='mm',kind='spatial_original_vertex_preview',
            source_path=self.old(self.model),source_sha256=file_sha256(self.model),source_vertex_count=4,preview_points=4,
            output_sha256={'preview-data.npz':file_sha256(folder/'preview-data.npz')})),encoding='utf-8')
        before=manifest.read_bytes();studio=Studio(self.root)
        model=next(row for row in studio.models.values() if row['path']==str(self.model))
        cloud=studio.cloud(model['id'],100)
        self.assertIn('缓存',cloud['selection']);np.testing.assert_array_equal(np.frombuffer(base64.b64decode(cloud['xyz']),'<f4').reshape(-1,3),self.xyz)
        self.assertEqual(manifest.read_bytes(),before)

    def test_restored_running_job_is_interrupted_and_does_not_block_new_work(self):
        folder=self.root/'reports/web-studio/runs/stopped';folder.mkdir(parents=True)
        record=folder/'job.json';record.write_text(json.dumps(dict(id='stopped',folder=self.old(folder),kind='spatial',status='running')),encoding='utf-8')
        before=record.read_bytes();studio=Studio(self.root)
        self.assertEqual(studio.job('stopped')['status'],'interrupted')
        self.assertEqual(studio.job('stopped')['restored_status'],'running')
        model=next(iter(studio.models))
        with patch('reconstruction_probe.web_studio.threading.Thread'):
            job=studio.start_job(dict(kind='spatial',model_id=model))
        self.assertEqual(job['status'],'queued');self.assertEqual(record.read_bytes(),before)

    def make_workbench(self):
        page=self.study/'experiments/pair/workbench.html';page.parent.mkdir(parents=True)
        candidate=page.with_name('candidate.json');candidate.write_text(json.dumps(dict(candidates=[dict(label='identity',transform=np.eye(4).tolist())])),encoding='utf-8')
        data=dict(preparedPath=None,candidateReference=dict(path=self.old(candidate),sha256=file_sha256(candidate)),clouds=[
            dict(path=self.old(self.model),originalPoints=4,label='moving'),
            dict(path=CAPTURE_ROOT+r'\uuid\pointclouds\fuse.ply',originalPoints=4,label='fixed')])
        page.write_text('<script id="alignment-data" type="application/json">'+json.dumps(data)+'</script>',encoding='utf-8')
        return page,candidate

    def test_runtime_html_and_post_session_map_paths_but_preserve_candidate_hash(self):
        page,candidate=self.make_workbench();before={p:p.read_bytes() for p in [page,candidate,self.index]}
        studio=Studio(self.root);payload=studio.workbench_data(studio.static_bytes(page).decode('utf-8'))
        self.assertEqual(payload['clouds'][0]['path'],str(self.model))
        self.assertEqual(payload['candidateReference']['sha256'],file_sha256(candidate))
        session=dict(kind='existing_candidate',source=dict(path=self.old(self.model)),
            target=dict(path=CAPTURE_ROOT+r'\uuid\pointclouds\fuse.ply'),
            candidate_reference=dict(path=self.old(candidate),sha256=file_sha256(candidate)))
        with patch('reconstruction_probe.web_studio.threading.Thread'):
            result=studio.start_job(dict(kind='alignment',session=session))
        written=json.loads((Path(result['folder'])/'session.json').read_text(encoding='utf-8'))
        self.assertEqual(written['source']['path'],str(self.model));self.assertEqual(written['candidate_reference']['sha256'],file_sha256(candidate))
        self.assertIn('reconstruction_probe.path_mapping',result['command_argv'])
        self.assertEqual(session['source']['path'],self.old(self.model),'request objects are not rewritten in place')
        for path,content in before.items():self.assertEqual(path.read_bytes(),content)

    def test_stale_candidate_and_outside_session_cannot_create_job(self):
        page,candidate=self.make_workbench();studio=Studio(self.root)
        session=dict(kind='existing_candidate',source=dict(path=self.old(self.model)),target=dict(path=str(self.official)),
            candidate_reference=dict(path=self.old(candidate),sha256='stale'))
        with self.assertRaisesRegex(ValueError,'字节'):studio.start_job(dict(kind='alignment',session=session))
        self.assertFalse(studio.output.exists())
        session['candidate_reference']['sha256']=file_sha256(candidate);session['source']['path']=PROJECT_ROOTS[0]+r'\..\outside.ply'
        with self.assertRaises(ValueError):studio.start_job(dict(kind='alignment',session=session))
        self.assertFalse(studio.output.exists())

    def test_incomplete_files_are_isolated_and_http_refresh_discovers_new_model(self):
        broken=self.study/'reconstruction/scan_broken/tsdf_pointcloud_mm.ply';broken.parent.mkdir(parents=True);broken.write_bytes(b'ply\n')
        bad_index=self.study/'decoded/broken/index.json';bad_index.parent.mkdir(parents=True);bad_index.write_bytes(b'{')
        bad_page=self.study/'experiments/incomplete/workbench.html';bad_page.parent.mkdir(parents=True);bad_page.write_text('<script id="alignment-data" type="application/json">{</script>')
        studio=Studio(self.root)
        self.assertTrue({'index','model','workbench'}<={row['kind'] for row in studio.catalog['availability']['missing']})
        new=self.study/'reconstruction/scan_new/tsdf_pointcloud_mm.ply';new.parent.mkdir(parents=True);shutil.copyfile(self.model,new)
        old_count=len(studio.models)
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(studio));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            with urlopen(f'http://127.0.0.1:{server.server_port}/api/catalog?refresh=1') as response:catalog=json.load(response)
            self.assertEqual(catalog['summary']['models'],old_count+1)
        finally:server.shutdown();server.server_close();worker.join()


if __name__=='__main__':unittest.main()
