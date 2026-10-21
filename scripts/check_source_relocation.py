"""Read-only hash audit of relocated original scans against saved decode snapshots."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decoded',default='reports/range2-study-20261018/decoded')
    parser.add_argument('--out',required=True)
    args=parser.parse_args();root=Path(__file__).resolve().parents[1];mapper=PathMapper(root)
    decoded=mapper.resolve(args.decoded);out=mapper.resolve_output(args.out)
    if out.exists() or root/'reports' not in out.parents:parser.error('Use a new report strictly within workspace/reports')
    rows=[];total=0;size=0;index_pins={}
    for path in sorted(decoded.glob('*/index.json')):
        index=json.loads(path.read_text(encoding='utf-8'));index_pins[str(path)]=file_sha256(path)
        expected=index.get('source_hashes_before')
        if not isinstance(expected,dict) or not expected:raise ValueError('Index has no original source snapshot: '+str(path))
        records=[]
        for old,sha in expected.items():
            current=mapper.resolve(old);row=dict(original_path=old,resolved_path=str(current),expected_sha256=sha)
            if not current.is_file():row['status']='missing'
            else:
                before=current.stat();actual=file_sha256(current);after=current.stat()
                row.update(actual_sha256=actual,bytes=after.st_size,
                    status='unchanged' if actual==sha and (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns) else 'changed_or_unstable')
                size+=after.st_size
            total+=1;records.append(row)
        rows.append(dict(scan_id=index['scan_id'],source_files=len(records),records=records))
        print(json.dumps(dict(scan_id=index['scan_id'],checked=len(records),problems=sum(r['status']!='unchanged' for r in records))),flush=True)
    if not rows:raise ValueError('No decoded source snapshots were found')
    for name,sha in index_pins.items():
        if file_sha256(Path(name))!=sha:raise ValueError('Input snapshot changed during audit: '+name)
    summary=dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),projects=len(rows),required_source_files=total,
        source_bytes_read=size,all_required_source_files_match=all(r['status']=='unchanged' for row in rows for r in row['records']),
        source_files_never_written=True,index_sha256=index_pins,records=rows,
        limitations=['Checks original files named by each immutable decode snapshot; unlisted newly added files are not certified.',
            'This is file-content identity after relocation, not scanner geometric accuracy or decoded-frame completeness.'])
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:summary[key] for key in ['projects','required_source_files','source_bytes_read','all_required_source_files_match']}),flush=True)
    if not summary['all_required_source_files_match']:raise SystemExit(1)


if __name__=='__main__':main()
