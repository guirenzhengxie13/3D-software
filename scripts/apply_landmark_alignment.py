"""Verify a workbench export and save new aligned surfaces and transform records."""

import os
os.environ.setdefault("OMP_NUM_THREADS","4")

import argparse
import copy
import json
from pathlib import Path
import re

import numpy as np
import open3d as o3d

from reconstruction_probe.landmark_sessions import verify_landmark_session
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.sources import _read_ply_cloud
from register_scans import preprocess,refine,metrics,score,save_json


def read(path):return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--session",type=Path,required=True);parser.add_argument("--out",type=Path,required=True);parser.add_argument("--refine-icp",action="store_true")
    args=parser.parse_args();session_path=args.session.resolve();out=args.out.resolve();session=read(session_path)
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    source_path=Path(session["source"]["path"]).resolve();target_path=Path(session["target"]["path"]).resolve()
    source=_read_ply_cloud(o3d,source_path);target=_read_ply_cloud(o3d,target_path)
    source_sha,target_sha=file_sha256(source_path),file_sha256(target_path)
    validated=verify_landmark_session(session,np.asarray(source.points),np.asarray(target.points),source_sha,target_sha)
    inputs={str(p):file_sha256(p) for p in [session_path,source_path,target_path]}
    prepared=Path(session["prepared_path"]).resolve() if session.get("prepared_path") else None
    if prepared:
        training=read(prepared/"training.json");paths={row["id_high"]:Path(row["path"]).resolve() for row in training["groups"]}
        if paths.get(1)!=source_path or paths.get(0)!=target_path:raise ValueError("Prepared fragment source/target mismatch")
        inputs[str(prepared/"split.json")]=file_sha256(prepared/"split.json")
    if validated["kind"]=="existing_candidate":
        reference=session.get("candidate_reference",{})
        if not isinstance(reference,dict) or not reference.get("path"):raise ValueError("Existing transform requires its recorded candidate file")
        path=Path(reference["path"]).resolve()
        if file_sha256(path)!=reference.get("sha256"):raise ValueError("Existing candidate record changed")
        recorded=[row for row in read(path)["candidates"] if row["label"]==session.get("candidate_label")]
        if len(recorded)!=1 or not np.allclose(np.array(recorded[0]["transform"]),validated["matrix"],rtol=0,atol=1e-10):raise ValueError("Exported existing candidate does not match its record")
        inputs[str(path)]=file_sha256(path)
    label="manual_landmarks" if validated["kind"]=="manual_landmarks" else "selected_"+session["candidate_label"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}",label):raise ValueError("Unsupported candidate label")
    out.mkdir(parents=True,exist_ok=True)
    fine_s,_=preprocess(source,.5);fine_t,_=preprocess(target,.5)
    candidates=[dict(label=label,transform=validated["matrix"].tolist(),selection=validated["note"])]
    if args.refine_icp:
        matrix,details=refine(fine_s,fine_t,validated["matrix"],[3.,1.5,1.],iterations=55)
        candidates.append(dict(label=label+"_icp",transform=matrix.tolist(),selection="Optional surface ICP after selected landmarks; initial landmark fit preserved",**details))
    for row in candidates:
        matrix=np.array(row["transform"]);values=metrics(fine_s,fine_t,matrix,[1.,2.5,5.]);row.update(surface_training_metrics=values,surface_training_score=score(values,[1.,2.5,5.]))
        aligned=copy.deepcopy(source).transform(matrix);path=out/(row["label"]+"-aligned-mm.ply");o3d.io.write_point_cloud(str(path),aligned);row["aligned_path"]=str(path)
    validation={k:v for k,v in validated.items() if k!="matrix"}
    save_json(out/"summary.json",dict(reference_group=session.get('target',{}).get('fragment_id',0),moving_group=session.get('source',{}).get('fragment_id',1),
        target_fragment_id=session.get('target',{}).get('fragment_id',0),source_fragment_id=session.get('source',{}).get('fragment_id',1),prepared_path=str(prepared) if prepared else None,candidates=candidates,
        input_sha256=inputs,landmark_validation=validation,status="reviewable_candidates_not_automatically_promoted",
        limitations=["Landmark residuals describe chosen pairs and may be small despite an incorrect physical correspondence.",
          "Optional ICP metrics are fitted on the same supplied surfaces, not independent accuracy validation.",
          "Only separate derived surfaces and transforms are saved; source PLY and source poses remain unchanged."]))
    (out/"session-original.json").write_bytes(session_path.read_bytes())
    print(json.dumps(dict(output=str(out),landmark_validation=validation,candidates=[row['label'] for row in candidates]),ensure_ascii=False))


if __name__=="__main__":main()
