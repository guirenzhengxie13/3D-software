"""Run an explicit offline reconstruction recipe with recorded tool calls."""

import argparse
import json
from pathlib import Path

from reconstruction_probe.workflow import run_workflow, tool_catalog, validate_plan
from build_workflow_run_report import build


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--plan', type=Path); parser.add_argument('--out', type=Path)
    parser.add_argument('--cancel-file', type=Path); parser.add_argument('--validate-only', action='store_true'); parser.add_argument('--list-tools', action='store_true')
    args = parser.parse_args(); workspace = Path(__file__).resolve().parents[1]
    if args.list_tools:
        print(json.dumps(tool_catalog(), ensure_ascii=False, indent=2)); return
    if args.plan is None:
        parser.error('--plan is required unless --list-tools is used')
    if args.out is None:
        if not args.validate_only:parser.error('--out is required for execution')
    try:
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        if args.validate_only:
            validate_plan(plan, workspace); print(json.dumps(dict(status='valid', operations=len(plan['nodes'])))); return
        state = run_workflow(plan, workspace, args.out, args.cancel_file,
            on_event=lambda event:print(json.dumps(event, ensure_ascii=False), flush=True))
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps(dict(status='rejected',error=str(error)),ensure_ascii=False));raise SystemExit(2)
    report=build(args.out)
    print(json.dumps(dict(status=state['status'], completed=sum(n['status']=='completed' for n in state['nodes']), not_run=state['not_run_operations'],report=str(report)), ensure_ascii=False))
    if state['status'] == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
