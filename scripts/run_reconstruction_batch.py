"""Run independent TSDF jobs, retaining failures and completed job parameters."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from reconstruct_scans import reconstruct, write_json
from reconstruction_probe.offline import file_sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--scans", nargs="+")
    parser.add_argument("--voxel-mm", type=float, default=.6)
    parser.add_argument("--truncation-mm", type=float, default=2.4)
    parser.add_argument("--edge-mm", type=float, default=3.)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--pose-policy", choices=("auto", "stored", "optimized"), default="optimized")
    parser.add_argument("--skip-existing", action="store_true", help="Reuse only jobs whose recorded parameters match this invocation")
    args = parser.parse_args()
    if args.voxel_mm <= 0 or args.truncation_mm <= args.voxel_mm or args.stride < 1:
        parser.error("Positive voxel/stride and truncation greater than voxel required")
    decoded, output = args.decoded.resolve(), args.out.resolve()
    if decoded == output or decoded in output.parents or output in decoded.parents:
        parser.error("Keep output separate from decoded inputs")
    output.mkdir(parents=True, exist_ok=True)
    indices = sorted(decoded.glob("*/index.json"))
    results = []
    for path in indices:
        index = json.loads(path.read_text(encoding="utf-8"))
        scan_id = index["scan_id"]
        if args.scans and scan_id not in args.scans:
            continue
        if not index.get("status", {}).get("depth_decoded"):
            results.append({"scan_id": scan_id, "status": "empty_saved_depth_project"})
            continue
        previous = output / scan_id / "reconstruction.json"
        try:
            if args.skip_existing and previous.exists():
                report = json.loads(previous.read_text(encoding="utf-8"))
                expected = {"requested_voxel_mm": args.voxel_mm, "frame_stride": args.stride,
                    "depth_edge_threshold_mm": args.edge_mm, "pose_policy": args.pose_policy}
                if any(report.get(k) != v for k, v in expected.items()):
                    raise ValueError("Existing job has different parameters; choose another output root")
                if report.get("source_directory") != index["source_directory"]:
                    raise ValueError("Existing job has different source provenance")
                if report.get("tsdf_backend", "uniform") != "uniform":
                    raise ValueError("Existing job uses another TSDF backend")
                if report.get("decoded_index_sha256") != file_sha256(path):
                    raise ValueError("Decoded index changed or its original hash was not recorded")
                if not all((previous.parent / name).exists() for name in ("tsdf_pointcloud_mm.ply", "tsdf_mesh_mm.ply", "tsdf_mesh_mm.obj")):
                    raise ValueError("Existing result is incomplete")
                # The current report records effective truncation. Compare to
                # the computed maximum rather than pretending it is requested.
                if abs(report["sdf_truncation_mm"] - max(args.truncation_mm, report["voxel_mm"] * 4)) > 1e-9:
                    raise ValueError("Existing truncation does not match invocation")
                results.append({"scan_id": scan_id, "status": "reused_matching_job"})
            else:
                started = time.time()
                report = reconstruct(path.parent, output, args.voxel_mm, args.truncation_mm,
                    args.edge_mm, args.stride, args.pose_policy != "stored", pose_policy=args.pose_policy)
                results.append({"scan_id": scan_id, "status": "reconstructed", "elapsed_seconds": time.time()-started,
                    "integrated_frames": report["integrated_frames"], "quality": report["quality"]})
        except Exception as exc:
            results.append({"scan_id": scan_id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            print(json.dumps(results[-1]), flush=True)
        write_json(output / "batch-status.json", results)
    write_json(output / "batch-status.json", results)
    completed = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(output.glob("*/reconstruction.json"))]
    write_json(output / "reconstruction_summary.json", [{k: v for k, v in r.items() if k != "frames"} for r in completed])
    print(json.dumps({"completed": len(completed), "failures": sum(r["status"]=="failed" for r in results)}), flush=True)


if __name__ == "__main__":
    main()
