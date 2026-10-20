"""Synthetic cache -> generated UI logic -> original-point backend control."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np

from reconstruction_probe.lod_cache import load_lod_cache,write_vertex_preview_ply
from reconstruction_probe.offline import file_sha256


def main():
    workspace=Path(__file__).resolve().parents[1];cache=(workspace/'.cache').resolve();cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cached-landmark-control-',dir=cache) as temporary:
        root=Path(temporary).resolve()
        if cache not in root.parents:raise ValueError('Temporary control escaped intended workspace cache')
        inputs=root/'unicode-inputs-点云';inputs.mkdir();rng=np.random.default_rng(456)
        source=rng.integers(-50,51,(500,3)).astype(float)+[0,0,500];matrix=np.array([[0.,-1,0,20],[1,0,0,-10],[0,0,1,3],[0,0,0,1]])
        target=source@matrix[:3,:3].T+matrix[:3,3];rgb=rng.integers(0,256,(500,3),dtype=np.uint8);paths={}
        for name,xyz in [('source',source),('target',target)]:
            path=inputs/(name+'.ply');write_vertex_preview_ply(path,xyz.astype(np.float32),rgb,np.arange(500));paths[name]=path
            subprocess.run([sys.executable,'scripts/build_pointcloud_lod.py','--source',str(path),'--unit','mm','--budget','100','--out',str(root/(name+'-cache'))],cwd=workspace,check=True,stdout=subprocess.DEVNULL)
        # Deliberately choose high original IDs not guaranteed to be present
        # in the new spatial cache, exercising selected-point retention.
        selected=[401,417,469,499];session=dict(format_version=1,unit='mm',kind='manual_landmarks',prepared_path=None,
            source=dict(path=str(paths['source']),sha256=file_sha256(paths['source']),fragment_id=1),
            target=dict(path=str(paths['target']),sha256=file_sha256(paths['target']),fragment_id=0),
            transform_source_to_target=matrix.tolist(),point_pairs=[dict(source=dict(id=i,xyz=source[i].tolist()),target=dict(id=i,xyz=target[i].tolist())) for i in selected],
            fixture='Synthetic known rigid transform; no human annotations')
        session_path=root/'synthetic-session.json';session_path.write_text(json.dumps(session),encoding='utf-8')
        page=root/'workbench.html'
        subprocess.run([sys.executable,'scripts/build_landmark_workbench.py','--source-cloud',str(paths['source']),'--target-cloud',str(paths['target']),
            '--source-lod',str(root/'source-cache'),'--target-lod',str(root/'target-cache'),'--max-points','200','--unit','mm','--include-session',str(session_path),'--out',str(page)],cwd=workspace,check=True,stdout=subprocess.DEVNULL)
        exported=root/'exported-session.json'
        subprocess.run(['C:/Program Files/nodejs/node.exe','tests/check_cached_landmark_export.cjs',str(page),str(session_path),str(exported)],cwd=workspace,check=True)
        output=root/'backend-result'
        subprocess.run([sys.executable,'scripts/apply_landmark_alignment.py','--session',str(exported),'--out',str(output)],cwd=workspace,check=True,stdout=subprocess.DEVNULL)
        report=json.loads((output/'summary.json').read_text(encoding='utf-8'));np.testing.assert_allclose(report['candidates'][0]['transform'],matrix,atol=1e-8)
        if report['landmark_validation']['rmse_mm']>1e-8:raise ValueError('Original-point landmark solve did not recover known rigid control')
        print(json.dumps(dict(fixture='synthetic_only',spatial_caches=True,earlier_original_landmarks_retained=True,generated_html_ui_logic_export=True,
            original_file_backend_verified=True,unicode_source_paths=True,physical_accuracy_verified=False,actual_gpu_verified=False)),flush=True)


if __name__=='__main__':main()
