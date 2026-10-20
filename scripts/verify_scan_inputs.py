"""Check original file hashes and supplied ZIP CRCs without changing inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe.offline import file_sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", type=Path, default=Path("item"))
    parser.add_argument("--decoded", type=Path, default=Path("reports/four-scans/decoded"))
    parser.add_argument("--out", type=Path, default=Path("reports/four-scans/input-integrity.json"))
    args = parser.parse_args()
    source = args.item.resolve()
    if args.out.resolve().is_relative_to(source):
        parser.error("Write reports outside the source input directory")
    checks, archives = [], []
    for index in sorted(args.decoded.glob("scan_*/index.json")):
        data = json.loads(index.read_text(encoding="utf-8"))
        for name, before in data["source_hashes_before"].items():
            path = Path(name)
            current = file_sha256(path)
            checks.append({"scan": data["scan_id"], "path": str(path),
                           "sha256": current, "unchanged": current == before})
    for path in sorted(args.item.glob("*.zip")):
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            entries = [entry for entry in archive.infolist() if not entry.is_dir()]
            root = path.with_suffix("")
            matched, differences, missing = 0, [], []
            for entry in entries:
                target = (root / entry.filename).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError("Unsafe original archive path")
                if not target.is_file():
                    missing.append(entry.filename)
                    continue
                digest = hashlib.sha256()
                with archive.open(entry) as stream:
                    for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != file_sha256(target):
                    differences.append(entry.filename)
                else:
                    matched += 1
            archives.append({"path": str(path.resolve()), "sha256": file_sha256(path),
                             "crc_ok": bad is None, "first_bad_entry": bad,
                             "files": len(entries), "extracted_matching": matched,
                             "extracted_different": differences, "extracted_missing": missing})
            print(f"{path.name}: CRC {'ok' if bad is None else 'ERROR'}, matching extracted {matched}/{len(entries)}", flush=True)
    result = {"original_files_checked": len(checks), "all_original_files_unchanged": all(x["unchanged"] for x in checks),
              "all_archive_crcs_ok": all(x["crc_ok"] for x in archives),
              "all_extracted_files_match_archives": all(x["extracted_matching"] == x["files"] for x in archives),
              "archives": archives, "file_checks": checks}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in ("archives", "file_checks")}))
    if not result["all_original_files_unchanged"] or not result["all_archive_crcs_ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
