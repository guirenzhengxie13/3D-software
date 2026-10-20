"""Command-line smoke test and optional point-cloud window."""

import argparse
import json
from pathlib import Path
import sys

from .frames import PointCloudFrame
from .ply import write_ascii_ply
from .sources import PlyReplaySource, RevopointSource, SimulatedSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Point-cloud input probe; no Revopoint SDK is bundled")
    parser.add_argument("--source", choices=("simulate", "ply", "revopoint"), default="simulate")
    parser.add_argument("--headless", action="store_true", help="Inspect input without creating a window")
    parser.add_argument("--frames", type=int, default=90, help="Number of synthetic frames")
    parser.add_argument("--points", type=int, default=6000, help="Points in each synthetic frame")
    parser.add_argument("--fps", type=float, default=15.0, help="Preview/replay pacing; headless runs unpaced")
    parser.add_argument("--seed", type=int, default=7, help="Deterministic synthetic geometry seed")
    parser.add_argument("--ply", type=Path, nargs="+", help="PLY file(s) in desired replay order")
    parser.add_argument("--ply-unit", choices=("m", "mm"), help="Required for PLY; the unit is not inferred")
    parser.add_argument("--output-ply", type=Path, help="Save the last frame as ASCII PLY in metres")
    return parser


def _summary(frame: PointCloudFrame, source: str, frame_count: int) -> dict:
    return {
        "source": source,
        "hardware_verified": False,
        "frames_received": frame_count,
        "last_frame_id": frame.frame_id,
        "point_count": len(frame.xyz),
        "has_colors": frame.colors is not None,
        "xyz_unit": frame.unit,
        "coordinate_frame": frame.coordinate_frame,
        "timestamp": frame.timestamp,
        "timestamp_domain": frame.timestamp_domain,
        "bounds_min_m": frame.xyz.min(axis=0).tolist() if len(frame.xyz) else None,
        "bounds_max_m": frame.xyz.max(axis=0).tolist() if len(frame.xyz) else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.source == "revopoint":
            source = RevopointSource()
        elif args.source == "ply":
            if not args.ply or args.ply_unit is None:
                parser.error("--source ply requires --ply FILE [FILE ...] and --ply-unit m|mm")
            source = PlyReplaySource(args.ply, args.ply_unit, args.fps, not args.headless)
        else:
            source = SimulatedSource(args.points, args.frames, args.fps, args.seed, not args.headless)

        label = "SYNTHETIC DATA" if args.source == "simulate" else "OFFLINE PLY REPLAY"
        print(f"{label}: this run does not verify live scanner acquisition.", file=sys.stderr)
        received = 0

        def count_frames():
            nonlocal received
            for frame in source:
                received += 1
                yield frame

        last = None
        if args.headless:
            for last in count_frames():
                pass
        else:
            from .viewer import show_frames

            last = show_frames(count_frames(), f"Reconstruction Probe - {label}")
        if last is None:
            raise RuntimeError("The input returned no frames")
        if args.output_ply is not None:
            write_ascii_ply(args.output_ply, last)
        print(json.dumps(_summary(last, args.source, received), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
