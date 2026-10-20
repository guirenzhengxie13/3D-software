"""Compare browser quaternion fitting with the independent NumPy SVD solver."""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import numpy as np
from reconstruction_probe.marker_refinement import rigid_alignment


def main():
    node=shutil.which("node")
    if not node:raise RuntimeError("Node.js is required for browser-math verification")
    rng=np.random.default_rng(20261019);rows=[]
    for count in [3,4,8,20]:
        for case in range(20):
            points=rng.normal(size=(count,3))*50+rng.normal(size=(1,3))*500
            if case%3==0:points[:,2]=points[0,2]
            q,_=np.linalg.qr(rng.normal(size=(3,3)))
            if np.linalg.det(q)<0:q[:,0]*=-1
            target=points@q.T+rng.normal(size=3)*500
            if case%2:target+=rng.normal(size=target.shape)*.05
            matrix=rigid_alignment(points,target);delta=points@matrix[:3,:3].T+matrix[:3,3]-target
            rows.append(dict(source=points.tolist(),target=target.tolist(),expected=matrix.tolist(),rmse=float(np.sqrt(np.mean(np.sum(delta*delta,axis=1))))))
    with tempfile.TemporaryDirectory(prefix="landmark-math-") as directory:
        path=Path(directory)/"fixtures.json";path.write_text(json.dumps(rows,allow_nan=False),encoding="utf-8")
        subprocess.run([node,str(Path(__file__).resolve().parents[1]/"tests/check_landmark_math.cjs"),str(path)],check=True)


if __name__=="__main__":main()
