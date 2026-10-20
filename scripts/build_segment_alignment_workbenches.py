"""Prepare correspondence workbenches for rejected adjacent segment links."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from reconstruction_probe.offline import file_sha256


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--graph-study',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();study=args.graph_study.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);report=read(study/'summary.json');center=np.array(report['center_original_scan_mm']);segments={row['fragment_id']:row for row in report['segments']};rows=[]
    for edge in report['edges']:
        if edge['accepted'] or edge['uncertain']:continue
        source,target=edge['source'],edge['target'];folder=out/f'segment-{source}-to-{target}';folder.mkdir();matrix=np.array(edge['transform_m']);matrix[:3,3]=center+1000*matrix[:3,3]-matrix[:3,:3]@center
        paths=[Path(segments[target]['path']),Path(segments[source]['path'])]
        candidates=dict(candidates=[dict(label='original_segment_positions',transform=np.eye(4).tolist()),dict(label='geometric_candidate_failed_gates',transform=matrix.tolist())],
            source_fragment_id=source,target_fragment_id=target,original_gate_checks=edge['checks'],status='needs_correspondence_review',
            input_sha256={str(p):file_sha256(p) for p in [study/'summary.json',*paths]})
        (folder/'summary.json').write_text(json.dumps(candidates,ensure_ascii=False,indent=2),encoding='utf-8');page=folder/'workbench.html'
        command=[sys.executable,'scripts/build_landmark_workbench.py','--target-cloud',str(paths[0]),'--source-cloud',str(paths[1]),'--target-fragment-id',str(target),'--source-fragment-id',str(source),'--unit','mm','--registration',str(folder),'--out',str(page)]
        subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
        rows.append(dict(source_fragment_id=source,target_fragment_id=target,page=str(page),relative_page=page.relative_to(out).as_posix(),failed_checks=[name for name,passed in edge['checks'].items() if not passed]))
    (out/'summary.json').write_text(json.dumps(dict(graph_study=str(study),workbenches=rows,input_sha256={str(study/'summary.json'):file_sha256(study/'summary.json')}),ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 待审阅片段的对应点工作台','','自动配准未通过门槛的边单独保留。页面中的失败候选仅用于观察，不代表已被接受。可以指出同一物理位置，另存人工对应点变换。','','| 移动→固定片段 | 没通过的检查 | 工作台 |','| --- | --- | --- |']
    for row in rows:lines.append(f"| {row['source_fragment_id']} → {row['target_fragment_id']} | {', '.join(row['failed_checks'])} | [打开]({row['relative_page']}) |")
    lines+=['','导出后用 `scripts/apply_landmark_alignment.py --session 导出文件 --out 新目录` 核对原点并另存对齐。此阶段不自动覆盖原位姿或拼接不可靠的图。实际 GPU 画面仍待验证，已有数值和模拟交互检查。']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(dict(workbenches=len(rows)),ensure_ascii=False))


if __name__=='__main__':main()
