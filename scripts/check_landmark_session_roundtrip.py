"""Exercise session verification and CLI export using explicitly synthetic data."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import open3d as o3d

from reconstruction_probe.offline import file_sha256


def main():
    workspace=Path(__file__).resolve().parents[1];cache=(workspace/".cache").resolve();cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="synthetic-landmark-check-",dir=cache) as directory:
        root=Path(directory).resolve()
        if cache not in root.parents:raise ValueError("Temporary fixture escaped intended workspace cache")
        rng=np.random.default_rng(123);source=rng.normal(size=(150,3))*20+[0,0,500]
        matrix=np.array([[0,-1,0,20],[1,0,0,-10],[0,0,1,3],[0,0,0,1]],float);target=source@matrix[:3,:3].T+matrix[:3,3]
        colors=rng.integers(0,256,(len(source),3))/255
        paths=[]
        for name,points in [("source",source),("target",target)]:
            pc=o3d.geometry.PointCloud();pc.points=o3d.utility.Vector3dVector(points);pc.colors=o3d.utility.Vector3dVector(colors)
            path=root/(name+".ply");o3d.io.write_point_cloud(str(path),pc);paths.append(path)
        source_path,target_path=paths;before={str(p):file_sha256(p) for p in paths}
        session=dict(format_version=1,unit="mm",kind="manual_landmarks",prepared_path=None,
            source=dict(path=str(source_path),sha256=before[str(source_path)]),target=dict(path=str(target_path),sha256=before[str(target_path)]),
            transform_source_to_target=matrix.tolist(),point_pairs=[dict(source=dict(id=i,xyz=source[i].astype(np.float32).astype(float).tolist()),target=dict(id=i,xyz=target[i].astype(np.float32).astype(float).tolist())) for i in [0,1,2,3,4,5]])
        session_path=root/"synthetic-session.json";session_path.write_text(json.dumps(session),encoding="utf-8")
        command=[sys.executable,str(workspace/"scripts/apply_landmark_alignment.py"),"--session",str(session_path),"--out",str(root/"result"),"--refine-icp"]
        result=subprocess.run(command,cwd=workspace,capture_output=True,text=True,encoding="utf-8")
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        report=json.loads((root/"result/summary.json").read_text(encoding="utf-8"));assert len(report["candidates"])==2
        initial=report["candidates"][0];aligned=o3d.io.read_point_cloud(initial["aligned_path"])
        np.testing.assert_allclose(np.asarray(aligned.points),target,atol=1e-8)
        np.testing.assert_allclose(np.asarray(aligned.colors),colors,atol=1/255)
        assert report["landmark_validation"]["rmse_mm"]<1e-10
        assert before=={str(p):file_sha256(p) for p in paths}
        session["source"]["sha256"]="wrong";bad=root/"bad-session.json";bad.write_text(json.dumps(session),encoding="utf-8")
        rejected=subprocess.run([sys.executable,str(workspace/"scripts/apply_landmark_alignment.py"),"--session",str(bad),"--out",str(root/"must-not-exist")],cwd=workspace,capture_output=True,text=True,encoding="utf-8")
        assert rejected.returncode!=0 and not(root/"must-not-exist").exists()
        print(json.dumps(dict(fixture="synthetic_only",manual_session_to_aligned_ply=True,optional_icp_preserves_initial=True,wrong_hash_rejected_before_output=True,originals_unchanged=True)))


if __name__=="__main__":main()
