"""Build an explicit saved-frame fusion plan from a verified workbench alignment."""

import argparse
import json
from pathlib import Path

from reconstruction_probe.fragment_bridge import build_fragment_plan
from reconstruction_probe.path_mapping import PathMapper


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decoded', required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--alignment', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    mapper = PathMapper(Path(__file__).resolve().parents[1])
    out = mapper.resolve_output(args.out)
    if out.exists() or mapper.root/'reports' not in out.parents:
        parser.error('Use a new output directory strictly within workspace/reports')
    plan, summary = build_fragment_plan(args.decoded, args.binding, args.alignment, args.candidate, mapper)
    out.mkdir(parents=True)
    (out/'binding-original.json').write_bytes(mapper.resolve(args.binding).read_bytes())
    for name, data in [('fragment-plan.json', plan), ('summary.json', summary)]:
        (out/name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
