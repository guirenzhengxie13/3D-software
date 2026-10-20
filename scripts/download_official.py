"""Download the two official RANGE 2 preparation files without executing them."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent / "downloads"
ITEMS = (
    ("RevoScan6-6.4.1.1088-windows-x86_64.exe", "https://dl.revopoint3d.com/softs/revoscan6/RevoScan6-6.4.1.1088-windows-x86_64.exe"),
    ("range2-quickstartguide-cn-v3.1-20260106.pdf", "https://dl.revopoint3d.com/document/range2/range2-quickstartguide-cn-v3.1-20260106.pdf"),
)


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, url in ITEMS:
        destination = ROOT / name
        if not destination.exists():
            partial = destination.with_suffix(destination.suffix + ".part")
            print(f"Downloading {name}", flush=True)
            with urlopen(Request(url, headers={"User-Agent": "Range2-Research-Setup/1.0"}), timeout=60) as response:
                expected = response.headers.get("Content-Length")
                received = 0
                with partial.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        received += len(chunk)
                if expected and received != int(expected):
                    raise OSError(f"Incomplete download: {received}/{expected} bytes")
            partial.replace(destination)
        digest = hashlib.sha256()
        with destination.open("rb") as saved:
            for chunk in iter(lambda: saved.read(1024 * 1024), b""):
                digest.update(chunk)
        manifest.append({
            "name": name,
            "url": url,
            "bytes": destination.stat().st_size,
            "sha256": digest.hexdigest(),
            "checked_utc": datetime.now(timezone.utc).isoformat(),
        })
        print(f"Ready: {name} ({destination.stat().st_size:,} bytes)", flush=True)
    (ROOT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
