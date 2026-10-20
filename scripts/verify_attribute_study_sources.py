"""Recheck source-file snapshots and verbatim JPEG recovery, without mutation."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from reconstruction_probe.offline import file_sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decoded", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    projects, source_count, jpeg_count = [], 0, 0
    for p in sorted(args.decoded.glob("*/index.json")):
        index = json.loads(p.read_text(encoding="utf-8"))
        source = Path(index["source_directory"]).resolve()
        output = args.out.resolve()
        if source == output or source in output.parents:
            raise ValueError("Never write verification output inside source projects")
        changed, missing, jpeg_mismatches = [], [], []
        hashes = index["source_hashes_before"]
        for name, digest in hashes.items():
            original = Path(name)
            source_count += 1
            if not original.is_file(): missing.append(name)
            elif file_sha256(original) != digest: changed.append(name)
        present = {str(f.resolve()) for f in source.rglob("*") if f.is_file()}
        additions = sorted(present-set(hashes))
        for frame in index["frames"]:
            if not frame.get("rgb_original_saved"):
                continue
            jpeg_count += 1
            recovered = p.parent/f"frame_{frame['id']:010d}"/"rgb_original.jpg"
            if not recovered.is_file() or file_sha256(recovered) != frame["rgb_original_sha256"]:
                jpeg_mismatches.append(frame["id"])
        projects.append({"scan_id": index["scan_id"], "files": len(hashes),
            "changed_source_files": changed, "missing_source_files": missing,
            "source_files_added_since_snapshot": additions,
            "recovered_jpeg_mismatches": jpeg_mismatches,
            "source_snapshot_unchanged": not(changed or missing or additions),
            "recovered_jpegs_unchanged": not jpeg_mismatches})
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "projects": len(projects),
        "source_files_checked": source_count, "recovered_jpeg_files_checked": jpeg_count,
        "all_source_snapshots_unchanged": all(p["source_snapshot_unchanged"] for p in projects),
        "all_recovered_jpegs_unchanged": all(p["recovered_jpegs_unchanged"] for p in projects),
        "records": projects}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "records"}))
    if not(report["all_source_snapshots_unchanged"] and report["all_recovered_jpegs_unchanged"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
