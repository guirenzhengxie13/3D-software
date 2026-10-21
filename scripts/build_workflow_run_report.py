"""Build a small review page from a recorded deterministic workflow run."""

import argparse
import html
import json
from pathlib import Path


TITLES = {'fragments.plan':'核对表面与原帧归属', 'fragments.fuse':'片段原深度重融合', 'multi_scan.fuse':'多工程原始深度融合', 'multi_scan.evidence':'各扫描的支持与冲突',
    'multi_scan.trace':'表面点回查原帧', 'multi_scan.pixel_sensitivity':'像素邻域敏感性',
    'multi_scan.local_planes':'轴向差与局部表面距离', 'landmarks.align':'对应点配准',
    'cloud.preview':'空间预览与原顶点映射','cloud.index':'局部完整点云索引','cloud.region':'按需读取局部原始顶点'}
STATUS = {'running':'执行中', 'completed':'已完成', 'failed':'失败，后续步骤停止',
    'cancelled_between_operations':'已在步骤之间取消', 'pending':'未执行'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def describe(summary, tool):
    if tool=='fragments.plan':
        return f"核对 {summary['selected_frames']} 帧，固定 {summary['target_frames']} 帧、移动 {summary['source_frames']} 帧，绑定 {summary['pinned_files']} 份输入哈希；计划尚不是融合结果。"
    if tool=='fragments.fuse':
        arm='原保存位姿控制组' if summary['saved_control'] else '片段校正候选'
        return f"{arm}，积分 {summary['selected_frames']} 条原始深度，生成 {summary['quality']['point_count']:,} 点。物理精度仍需独立证据。"
    if tool=='multi_scan.evidence':
        rows=summary['surface_results'];joint=next(r for r in rows if r['label']=='joint_raw_depth');n=joint['sample_count']
        return f"联合表面抽样 {n:,} 点：双方支持 {joint['category_counts']['both_projects_support']/n:.1%}，有重复冲突 {joint['repeated_conflict_samples']/n:.1%}。这是同源内部诊断。"
    if tool=='multi_scan.trace':
        values=summary['source_observation_counts'];parts=[f"第{i+1}份支持/冲突/遮挡 {r['support']}/{r['free_space_conflict']}/{r['occluded']}" for i,r in enumerate(values)]
        return f"抽样编号 {summary['sample_index']}，原联合模型点编号 {summary['original_joint_point_id']}。"+'；'.join(parts)+'。'
    if tool=='multi_scan.pixel_sensitivity':
        return f"原重复冲突 {summary['repeated_center_conflict_samples']:,} 点；至少三视图的有效邻域仍全部冲突 {summary['repeated_unanimous_neighbor_conflict_samples']:,} 点。未满足附加条件不表示已证明正确。"
    if tool=='multi_scan.local_planes':
        return f"原轴向重复冲突 {summary['original_repeated_axial_conflict_points']:,} 点；另有重复 >2 mm 法向偏差 {summary['repeated_additional_normal_discrepancy_points']:,} 点。未合格平面单独保留。"
    if tool=='multi_scan.fuse':
        joint=summary['results'][-1]
        return f"联合 {joint['integrated_frames']} 条保存深度，提取 {joint['quality']['point_count']:,} 个表面点。结果为待审阅候选。"
    if tool=='landmarks.align':
        return '已核对原文件与点编号，另存候选：'+', '.join(r['label'] for r in summary['candidates'])+'。'
    if tool=='cloud.preview':
        return f"原模型 {summary['source_vertex_count']:,} 点，空间预览 {summary['preview_points']:,} 点；所有显示点保留原始编号，完整模型不变。"
    if tool=='cloud.index':
        return f"索引 {summary['finite_source_points']:,} 个有效原始顶点，额外索引约 {summary['index_bytes']/2**20:.2f} MiB；没有丢弃顶点。"
    if tool=='cloud.region':
        return f"按 {len(summary['regions'])} 个区域取回 {summary['preview_points']:,} 个原始顶点；这是精确子集，未按预算偷偷抽样。"
    return ''


def build(root):
    root=root.resolve();state=read(root/'state.json');plan=read(root/'plan.json');by_id={r['id']:r for r in state['nodes']};cards=[];markdown=[]
    for ordinal,node in enumerate(plan['nodes'],1):
        row=by_id.get(node['id'],dict(status='pending'));status=row['status'];folder=root/'nodes'/node['id'];relative='nodes/'+node['id']+'/'
        description='';error=row.get('error','');summary_path=folder/'summary.json'
        if status=='completed' and summary_path.is_file():
            description=describe(read(summary_path),node['tool'])
        references=[v['node'] for v in node['parameters'].values() if isinstance(v,dict) and 'node' in v]
        links=[]
        for filename,label in [('review.html','三维审阅'),('README.md','方法与解释'),('summary.json','数值报告')]:
            if (folder/filename).is_file():links.append(f'<a href="{relative+filename}">{label}</a>')
        if row.get('log'):links.append(f'<a href="{html.escape(row["log"],quote=True)}">执行日志</a>')
        image=next((name for name in ['comparison.png','evidence.png'] if (folder/name).is_file()),None)
        picture=f'<img loading="lazy" src="{relative+image}" alt="{html.escape(TITLES[node["tool"]])}">' if image else ''
        timing=f" · {row['elapsed_seconds']:.1f} 秒" if 'elapsed_seconds' in row else ''
        dependency='<p class="muted">使用前序结果：'+html.escape(', '.join(dict.fromkeys(references)))+'</p>' if references else ''
        cards.append(f'<article class="{status}"><div class="stage">步骤 {ordinal} · {html.escape(node["id"])}</div><h2>{TITLES[node["tool"]]}</h2><p class="status">{STATUS.get(status,status)}{timing}</p>{dependency}<p>{html.escape(description)}</p>'+ (f'<p class="error">{html.escape(error)}</p>' if error else '')+picture+'<nav>'+' · '.join(links)+'</nav></article>')
        markdown += [f"## {ordinal}. {TITLES[node['tool']]} · {STATUS.get(status,status)}", '', description or error or '尚未执行。', '']
        if (folder/'README.md').is_file():markdown += [f'[方法与解释]({relative}README.md)', '']
        elif (folder/'summary.json').is_file():markdown += [f'[数值报告]({relative}summary.json)', '']
    title=plan.get('name') or '离线重建工作流';status=STATUS.get(state['status'],state['status'])
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>离线工具流程</title><style>
body{margin:0;background:#0c1420;color:#e2ecf8;font:16px/1.75 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1200px;margin:auto;padding:30px}h1{font-size:29px}h2{font-size:22px;margin:3px 0}a{color:#9bcaff}.muted,.stage{color:#adbed1;font-size:14px}.banner{padding:16px 20px;background:#203244;border-left:3px solid #8ac6e9;border-radius:5px}article{margin:22px 0;padding:22px;background:#17283b;border:1px solid #314b66;border-radius:10px}article.completed{border-left:4px solid #75bc9a}article.failed{border-left:4px solid #f08e7f}.status{color:#a4d5ff}.error{color:#ffb2a8}img{display:block;width:100%;max-height:650px;object-fit:contain;background:#101a27;border-radius:5px}nav{margin:14px 0}code{font-size:13px}</style><main>'''
    page+=f'<p class="muted">确定性工具与任务记录原型</p><h1>{html.escape(title)}</h1><p>{status} · 已完成 {sum(r["status"]=="completed" for r in state["nodes"])}/{len(plan["nodes"])} 步</p><div class="banner">本流程没有连接语言模型。每步另存结果，检查输入与依赖哈希；取消在步骤之间生效。以下证据均来自保存数据，不代表独立物理精度。</div><nav><a href="plan.json">处理配方</a> · <a href="state.json">执行状态与来源记录</a></nav>'
    page+=''.join(cards)+'<p class="muted">三维页面的实际 GPU 渲染仍待验证。执行时间使用 UTC，与扫描采集时间无关。此页是生成时的状态；运行中状态见 state.json，完成后可重新生成页面。</p></main></html>'
    (root/'index.html').write_text(page,encoding='utf-8')
    (root/'README.md').write_text('# '+title+'\n\n'+status+'。本流程执行确定性工具，没有调用语言模型；结果和处理状态可以审阅。\n\n[步骤与图片](index.html) · [配方](plan.json) · [执行记录](state.json)\n\n'+'\n'.join(markdown),encoding='utf-8')
    return root/'index.html'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,required=True);args=parser.parse_args()
    print(json.dumps(dict(report=str(build(args.run))),ensure_ascii=False))


if __name__=='__main__':main()
