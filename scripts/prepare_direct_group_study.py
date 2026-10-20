"""Build training-only fragment surfaces; reserve alternating record blocks."""

import os
os.environ.setdefault("OMP_NUM_THREADS","4")

import argparse
import json
from pathlib import Path

import numpy as np

from reconstruct_scans import reconstruct,optical_to_pose_axes,write_json
from experiment_color_seeded_roi import optical_points
from reconstruction_probe.offline import file_sha256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--block-size",type=int,default=16)
    args=parser.parse_args();root=args.study.resolve();out=args.out.resolve()
    if args.block_size<2:parser.error("At least two saved records per block")
    if out.exists() and any(out.iterdir()):parser.error("Use a new/empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    key="scan_20261018131359";decoded=root/"decoded"/key
    index=json.loads((decoded/"index.json").read_text(encoding="utf-8"))
    selection_path=root/"experiments/cup-roi"/(key+"-selection.json")
    roi=json.loads(selection_path.read_text(encoding="utf-8"));lower=np.array(roi["bounds_min_mm"]);upper=np.array(roi["bounds_max_mm"])
    groups={}
    for frame in index["frames"]:
        rid=frame["id"]
        if not frame.get("optimized_pose_available"):raise ValueError("This experiment requires saved optimized poses for every source record")
        groups.setdefault(rid>>32,[]).append(rid)
    if set(groups)!={0,1}:raise ValueError("Expected exactly the observed two ID groups")
    rows=[]
    for group,ids in sorted(groups.items()):
        fit=[rid for i,rid in enumerate(ids) if (i//args.block_size)%2==0]
        heldout=[rid for i,rid in enumerate(ids) if (i//args.block_size)%2==1]
        if not fit or not heldout or set(fit)&set(heldout) or set(fit)|set(heldout)!=set(ids):raise ValueError("Incomplete or overlapping split")
        rows.append(dict(id_high=group,all_ids=ids,training_ids=fit,heldout_ids=heldout,
                         saved_record_ordinals={str(rid):i for i,rid in enumerate(ids)}))
    report=dict(scan_id=key,block_size=args.block_size,record_order="Per-ID-high group index ordered by complete frame ID, not capture time",
        split_rule="Even numbered blocks train, odd numbered blocks are held out; no frame appears in both",
        groups=rows,roi_mm=dict(min=lower.tolist(),max=upper.tolist()),
        roi_provenance="Previously proposed from all source color observations; not a blind data-selection study",
        external_geometry_used=False,source_study=str(root),
        input_sha256={str(p):file_sha256(p) for p in [decoded/"index.json",selection_path]})
    write_json(out/"split.json",report)
    calibration=index["intrinsics"]["Pl"];signs=optical_to_pose_axes(index)
    def keep_roi(depth,matrix):
        ids,xyz=optical_points(depth,calibration);native=(xyz*signs)@matrix[:3,:3].T+matrix[:3,3]
        keep=np.all((native>=lower)&(native<=upper),axis=1);selected=depth.copy();selected.ravel()[ids[~keep]]=0
        return selected,int((~keep).sum())
    results=[]
    for row in rows:
        group=row["id_high"]
        poses={rid:np.load(decoded/f"frame_{rid:010d}"/"pose_optimized.npy",allow_pickle=False) for rid in row["training_ids"]}
        fitted=reconstruct(decoded,out/f"training-group-{group}",.6,2.4,3.,1,True,pose_overrides=poses,depth_filter=keep_roi,
            evaluate_vendor=False,bounds_override_mm=(lower,upper),tsdf_backend="tensor",tsdf_weight_threshold=3.,
            coordinate_frame="original_scan_20261018131359_mm",reconstruction_note=f"Direct fragment study: training-only ID group {group}; alternating index blocks of {args.block_size}; original poses and original ROI; no external reference geometry.")
        results.append(dict(id_high=group,integrated_frames=fitted["integrated_frames"],heldout_frames=len(row["heldout_ids"]),
            quality=fitted["quality"],path=str(out/f"training-group-{group}"/key/"tsdf_pointcloud_mm.ply")))
        print(json.dumps(results[-1]),flush=True)
    write_json(out/"training.json",dict(split_path=str(out/"split.json"),split_sha256=file_sha256(out/"split.json"),groups=results,
        limitations=["Held-out blocks are not statistically independent observations or physical truth.",
          "The earlier ROI used all source frames, while the actual fitting surfaces use training IDs only.",
          "ID-group meaning is not decoded; only a proposed rigid fragment relationship is investigated."]))


if __name__=="__main__":main()
