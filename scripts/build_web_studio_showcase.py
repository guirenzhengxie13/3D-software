"""Build a static success/candidate gallery alongside the local Web app."""
import html
import json
from pathlib import Path
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.web_studio import Studio


def main():
    root=Path(__file__).resolve().parents[1];out=root/'reports/web-studio';out.mkdir(parents=True,exist_ok=True);studio=Studio(root);catalog=studio.catalog
    items=[
        dict(title='彩色扫描：独立融合与官方同源比较',image='../range2-study-20261018/color-comparison.png',
             text='已从保存深度、颜色与位姿独立生成表面，并与同一工程的官方融合云对照。颜色通道按蓝色蝴蝶结实物信息校正；尚不能据此宣布物理精度优于官方。',url='../range2-study-20261018/official-fusion-comparison/comparison.html'),
        dict(title='两片段对齐后，用原始深度重新融合',image='../range2-study-20261018/experiments/cup-direct-split/full-reconstruction/comparison.png',
             text='同一工程358帧的演示减少了重复杯柄；训练/留出检查分别保留。孔洞和碎片仍存在，对应点工作台可进一步参与修正。',url='../range2-study-20261018/experiments/cup-direct-split/full-reconstruction/review.html'),
        dict(title='两次扫描：463帧进入同一个融合体',image='../range2-study-20261018/experiments/cup-multi-scan-tsdf/comparison.png',
             text='两份扫描7,208,475次有效深度观测，提取190,388个联合表面点。已区分两侧共同支持、各自补充和冲突，配准继续保留候选状态。',url='../range2-study-20261018/experiments/cup-multi-scan-tsdf/review.html'),
        dict(title='对应点网页：可用的兼容绘制路径',image='compatibility/workbench-canvas.png',
             text='6个已生成页面、18个视图通过WebGL缺失时的CPU实际像素检查，保留源文件、原编号和刚体变换。下图是离线CPU绘制产物，实际Chrome画面尚未核验。',url='http://127.0.0.1:8877/#alignment')]
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>交互辅助重建 · 当前成果</title><style>*{box-sizing:border-box}body{margin:0;background:#0d151f;color:#e0ecf7;font:16px/1.8 system-ui,'Microsoft YaHei',sans-serif}main{max-width:1380px;margin:auto;padding:36px}h1{font-size:32px;margin:5px 0 10px}h2{font-size:22px;margin:0 0 8px}p{color:#a3bbcf}a{color:#8edfc6}nav{display:flex;gap:15px;flex-wrap:wrap;margin:25px 0}.button{display:inline-block;background:#285d50;border:1px solid #65a48c;border-radius:7px;padding:12px 20px;color:#e5fff5;text-decoration:none}.secondary{background:#1a2c3f;border-color:#4d6f8d;color:#b6d7f0}.stats{display:flex;gap:15px;flex-wrap:wrap}.stats>div{padding:18px 25px;background:#162735;border:1px solid #30475c;border-radius:7px}.stats b{display:block;font-size:29px;color:#9fe4cd}.stats small{color:#9eb4c8}article{margin-top:28px;padding:25px;background:#152330;border:1px solid #30475b;border-radius:8px}img{width:100%;display:block;border-radius:7px;margin-top:18px;background:#111c28}.note{padding:17px 22px;background:#213447;border-radius:7px;border-left:3px solid #86bea9}code{background:#0d1721;padding:3px 7px}footer{margin-top:35px;color:#8da7bc}</style><main><p>面向三维扫描模型的交互式辅助重建软件 · 2026-10-20</p><h1>从离线工程，到可交互的 Web 工作台</h1><p>官方软件负责采集，自己的软件负责模型检查、局部处理、对应点配准、融合候选和可复现工作流。SDK实时接入保持后置。</p><nav><a class="button" href="http://127.0.0.1:8877/">进入 Web 工作台 ↗</a><a class="button secondary" href="../../docs/web-studio.md">启动与使用方法</a><a class="button secondary" href="../pointcloud-scale-20261019/index.html">点云规模与交互分层</a></nav>'''
    page+='<div class="stats">'+''.join(f'<div><b>{value}</b><small>{label}</small></div>' for value,label in [(catalog['summary']['projects'],'工程'),('11,932','保存深度帧'),('3.70亿','重复深度观测'),(len(catalog['experiments']),'类实验'),(len(catalog['workbenches']),'个对应点工作台')])+'</div>'
    page+='<p class="note">Web功能：模型图层、本地PLY浏览、保存帧回放、概览选点与局部完整点、对应点直接提交后端、实验图库和处理任务。WebGL不可用时可使用Canvas兼容绘制。目录、处理链与CPU实际像素已有检查；Chrome实机和GPU画面仍待验证。</p>'
    for item in items:
        for name in ['image']:
            if not (out/item[name]).is_file():raise ValueError('Showcase image missing: '+item[name])
        page+=f'<article><h2>{html.escape(item["title"])}</h2><p>{html.escape(item["text"])}</p><a href="{html.escape(item["url"])}">打开实际结果 ↗</a><img src="{html.escape(item["image"])}" alt="{html.escape(item["title"])}"></article>'
    page+='<footer>首次启动：项目根目录运行 <code>&amp; \'.\\scripts\\start-web-studio.ps1\'</code>，再打开本地工作台。独立研究页保留，开发模板不含模型数据。<p><a href="http-integration-check.json">真实HTTP检查</a> · <a href="compatibility/summary.json">兼容绘制记录</a> · <a href="validation.json">程序验证记录</a></p></footer></main></html>'
    (out/'index.html').write_text(page,encoding='utf-8')
    sources=[*sorted((root/'web/studio').glob('*')),root/'src/reconstruction_probe/web_studio.py',root/'scripts/serve_web_studio.py',root/'scripts/start-web-studio.ps1']
    (out/'implementation-sha256.json').write_text(json.dumps({str(p):file_sha256(p) for p in sources if p.is_file()},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(showcase=str(out/'index.html'),catalog=catalog['summary'],experiments=len(catalog['experiments']),workbenches=len(catalog['workbenches']))),flush=True)

if __name__=='__main__':main()
