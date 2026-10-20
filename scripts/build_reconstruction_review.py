"""Build a standalone, offline WebGL point-cloud review page.

Example (all PLY coordinates must use the explicitly supplied common unit):
  python scripts/build_reconstruction_review.py --unit mm \
    --cloud "原始解包=reports/parsed.ply" --cloud "重建结果=reports/fused.ply" \
    --out reports/review.html --notes "显示为抽样点云；请下载完整 PLY 评估细节。"

Overlay is disabled unless --allow-overlay is supplied for inputs already
known to share a coordinate system. This tool does not register or fuse data.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from reconstruction_probe._open3d import require_open3d
from reconstruction_probe.sources import _read_ply_cloud


HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:;">
<title>三维重建 · 离线结果审阅</title>
<style>
:root{color-scheme:dark;font-family:system-ui,"Microsoft YaHei",sans-serif;color:#e5edf6;background:#0b111b}
*{box-sizing:border-box}body{margin:0;height:100vh;display:flex;flex-direction:column;overflow:hidden}
header{height:65px;flex:none;padding:12px 20px;border-bottom:1px solid #293345;display:flex;align-items:center;justify-content:space-between;background:#101a28}
h1{font-size:18px;margin:0 0 4px;font-weight:650;letter-spacing:.04em}.subtitle{font-size:12px;color:#9bacbf}.offline{font-size:12px;background:#163b34;color:#9de1bf;padding:5px 10px;border-radius:20px}
main{display:flex;min-height:0;flex:1}aside{width:310px;flex-shrink:0;padding:18px;overflow:auto;background:#101925;border-right:1px solid #293345}
label{font-size:12px;color:#a6b8cc;display:block;margin:0 0 8px}.field{margin-bottom:20px}select,button{font:inherit;font-size:13px;color:#e5edf6;background:#1a293c;border:1px solid #3b4e64;border-radius:7px;padding:9px 10px}select{width:100%;cursor:pointer}button{cursor:pointer}button:hover{background:#263c56}.buttons{display:flex;gap:7px;flex-wrap:wrap}input[type=range]{width:100%;accent-color:#81b7f5}input[type=checkbox]{accent-color:#81b7f5}.check{display:flex;align-items:center;gap:7px;font-size:12px}
.stat{display:flex;justify-content:space-between;gap:10px;margin:9px 0;font-size:13px}.stat span:first-child{color:#95a9bf}.box{border-top:1px solid #29384b;padding-top:13px;margin-top:15px}.small{font-size:12px;line-height:1.7;color:#a7b9cc}.path{font-family:ui-monospace,monospace;font-size:11px;line-height:1.7;word-break:break-all;color:#869db8;margin-top:8px}.note{white-space:pre-wrap;color:#c4d2e1}.warn{padding:10px;border-radius:6px;background:#302b1b;color:#e0cb90;font-size:12px;line-height:1.6}.legend-row{display:flex;align-items:center;gap:8px;font-size:12px;line-height:1.9}.dot{width:9px;height:9px;border-radius:50%;flex:none}
#viewport{position:relative;flex:1;min-width:0;background:radial-gradient(ellipse at 50% 45%,#1b2c41,#0b111b 75%)}canvas{width:100%;height:100%;display:block;touch-action:none;outline:none}#title{position:absolute;top:20px;left:22px;font-size:15px;color:#dce9f8;pointer-events:none;max-width:calc(100% - 40px)}#hud{position:absolute;bottom:18px;left:20px;right:20px;font-size:12px;color:#9badc3;pointer-events:none;display:flex;justify-content:space-between;gap:15px}#error{display:none;position:absolute;inset:25% 10%;padding:20px;background:#331f25;border:1px solid #b66c7b;border-radius:10px;line-height:1.8}#sizeLegend{position:absolute;right:20px;top:20px;font-size:11px;color:#849ab5;pointer-events:none}.axis-label{font-size:11px;margin-top:10px;color:#9badc3}
@media(max-width:700px){header{height:58px;padding:10px 14px}h1{font-size:15px}.offline{display:none}aside{width:235px;padding:12px}.stat{font-size:11px}#hud{font-size:10px;left:10px}.subtitle{font-size:10px}}
</style></head><body>
<header><div><h1>三维重建 · 结果审阅</h1><div class="subtitle">离线点云预览 · 保留源坐标与物体比例</div></div><span class="offline">● 本地独立文件 · 无网络请求</span></header>
<main><aside>
<div class="field"><label for="model">审阅对象</label><select id="model"></select></div>
<div class="field"><label for="color">着色方式</label><select id="color"><option value="auto">自动（顶点色 / Z 高度色）</option><option value="model">按对象区分颜色</option></select></div>
<div class="field"><label for="pointSize">显示点大小 <span id="pointSizeValue">2.2</span></label><input id="pointSize" type="range" min="1" max="6" step="0.1" value="2.2"></div>
<div class="buttons"><button id="reset">适配视图</button><button id="front">正视 XZ</button><button id="top">俯视 XY</button></div>
<label class="check" style="margin:15px 0"><input id="axes" type="checkbox" checked> 显示坐标轴（X 红 / Y 绿 / Z 蓝）</label>
<div id="overlayNote" class="warn"></div>
<div class="box" id="stats"></div><div id="legend" class="box"></div>
<div class="box"><label>数据来源</label><div id="provenance" class="small note"></div><div id="paths" class="path"></div></div>
<div class="box"><label>审阅说明</label><div class="small note" id="notes"></div><p class="small">页面只对显示数据做确定性抽样。孔洞、噪点与精细表面质量应结合完整 PLY 和处理报告判断。</p></div>
</aside><section id="viewport"><canvas id="canvas" tabindex="0" aria-label="可旋转缩放的三维点云"></canvas><div id="title"></div><div id="sizeLegend"></div><div id="hud"><span>拖动旋转 · Shift + 拖动 / 右键平移 · 滚轮缩放</span><span id="viewStatus"></span></div><div id="error"></div></section></main>
<script id="review-data" type="application/json">__PAYLOAD__</script>
<script>
'use strict';
const DATA=JSON.parse(document.getElementById('review-data').textContent);
const $=id=>document.getElementById(id), canvas=$('canvas');
const palette=[[.40,.72,1],[1,.66,.38],[.49,.86,.65],[.86,.58,.96],[1,.47,.58],[.92,.85,.44]];
const models=DATA.clouds;
const upAxis=DATA.upAxis||'z';
const upSign=DATA.invertUp?-1:1;
function upVector(){return upAxis==='x'?[upSign,0,0]:upAxis==='y'?[0,upSign,0]:[0,0,upSign];}
function viewDirection(){const a=Math.cos(yaw)*Math.cos(pitch),b=Math.sin(yaw)*Math.cos(pitch),c=Math.sin(pitch)*upSign;return upAxis==='x'?[c,a,b]:upAxis==='y'?[b,c,a]:[a,b,c];}
$('front').textContent='正视 '+(upAxis==='y'?'XY':'XZ');
$('top').textContent='俯视 '+(upAxis==='x'?'YZ':upAxis==='y'?'XZ':'XY');
for(let i=0;i<models.length;i++){const option=document.createElement('option');option.value=String(i);option.textContent=models[i].label;$('model').appendChild(option);}
if(DATA.allowOverlay&&models.length>1){const option=document.createElement('option');option.value='all';option.textContent='叠加全部（共同坐标系）';$('model').appendChild(option);}
$('overlayNote').textContent=DATA.allowOverlay?'已启用叠加审阅；坐标是否一致由生成页面时的输入决定。':'各结果逐项查看；页面未假定不同扫描具有共同坐标系。';
$('notes').textContent=DATA.notes||'拖动查看整体结构，切换结果对比完整度与异常区域。';
$('provenance').textContent=DATA.provenance;
function decode64(text,type){const binary=atob(text),bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);if(type==='u8')return bytes;const values=new Float32Array(bytes.length/4),view=new DataView(bytes.buffer);for(let i=0;i<values.length;i++)values[i]=view.getFloat32(i*4,true);return values;}
const gl=canvas.getContext('webgl',{antialias:true,alpha:true});
function fatal(message){$('error').style.display='block';$('error').textContent=message;}
if(!gl){fatal('当前浏览器无法创建 WebGL 画布。请在启用硬件加速的浏览器中打开这个本地 HTML 文件。');throw new Error('WebGL unavailable');}
function shader(type,source){const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;}
let program;
const vertexShaderSource=`precision highp float;
attribute vec3 aPosition;attribute vec3 aColor;uniform mat4 uMVP;uniform float uPointSize;uniform float uTintMode;uniform vec3 uTint;varying mediump vec3 vColor;void main(){gl_Position=uMVP*vec4(aPosition,1.0);gl_PointSize=uPointSize;vColor=mix(aColor,uTint,uTintMode);}`;
const fragmentShaderSource=`precision mediump float;
uniform float uIsPoint;varying mediump vec3 vColor;void main(){if(uIsPoint>.5&&length(gl_PointCoord-vec2(.5))>.5)discard;gl_FragColor=vec4(vColor,1.0);}`;
try{program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertexShaderSource));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragmentShaderSource));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));}catch(error){fatal('三维着色器初始化失败：'+error.message);throw error;}
gl.useProgram(program);gl.enable(gl.DEPTH_TEST);gl.clearColor(0,0,0,0);
const loc={p:gl.getAttribLocation(program,'aPosition'),c:gl.getAttribLocation(program,'aColor'),mvp:gl.getUniformLocation(program,'uMVP'),size:gl.getUniformLocation(program,'uPointSize'),tintMode:gl.getUniformLocation(program,'uTintMode'),tint:gl.getUniformLocation(program,'uTint'),isPoint:gl.getUniformLocation(program,'uIsPoint')};
function upload(data){const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,data,gl.STATIC_DRAW);return b;}
for(let i=0;i<models.length;i++){const m=models[i];m.positionBuffer=upload(decode64(m.xyz,'f32'));m.colorBuffer=upload(decode64(m.rgb,'u8'));m.palette=palette[i%palette.length];delete m.xyz;delete m.rgb;}
function subtract(a,b){return a.map((v,i)=>v-b[i]);}function dot(a,b){return a.reduce((s,v,i)=>s+v*b[i],0);}function cross(a,b){return[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];}function normalized(a){const n=Math.hypot(...a);return a.map(v=>v/n);}
function multiply(a,b){const r=new Float32Array(16);for(let c=0;c<4;c++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)r[c*4+row]+=a[k*4+row]*b[c*4+k];return r;}
function perspective(aspect,near,far){const f=1/Math.tan(Math.PI/7.2),nf=1/(near-far);return new Float32Array([f/aspect,0,0,0,0,f,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0]);}
let yaw=-1.15,pitch=.38,distance=1,radius=1,target=[0,0,0],bounds,dirty=true,axisPosition=null,axisColor=null;
function selected(){return $('model').value==='all'?models:[models[Number($('model').value)]];}
function format(n){return Number(n).toLocaleString('zh-CN',{maximumFractionDigits:2});}
function stat(label,value){const row=document.createElement('div');row.className='stat';const a=document.createElement('span'),b=document.createElement('span');a.textContent=label;b.textContent=value;row.append(a,b);$('stats').appendChild(row);}
function fit(resetAngles=true){const current=selected();bounds={min:[Infinity,Infinity,Infinity],max:[-Infinity,-Infinity,-Infinity]};for(const m of current)for(let j=0;j<3;j++){bounds.min[j]=Math.min(bounds.min[j],m.bounds.min[j]);bounds.max[j]=Math.max(bounds.max[j],m.bounds.max[j]);}target=bounds.min.map((v,i)=>(v+bounds.max[i])/2);radius=Math.max(Math.hypot(...subtract(bounds.max,bounds.min))/2,1e-6);const aspect=Math.max(canvas.clientWidth,1)/Math.max(canvas.clientHeight,1);distance=radius*2.9*Math.max(1,1/aspect);if(resetAngles){yaw=upAxis==='y'?.55:-1.15;pitch=.28;}const length=radius*.35,anchor=bounds.min;const positions=[],colors=[];for(let j=0;j<3;j++){const end=anchor.slice();end[j]+=length;positions.push(...anchor,...end);for(let k=0;k<2;k++)colors.push(...[j===0?255:50,j===1?235:65,j===2?255:65]);}if(axisPosition)gl.deleteBuffer(axisPosition);if(axisColor)gl.deleteBuffer(axisColor);axisPosition=upload(new Float32Array(positions));axisColor=upload(new Uint8Array(colors));$('stats').replaceChildren();stat('原文件点数',format(current.reduce((n,m)=>n+m.originalPoints,0)));stat('显示抽样点数',format(current.reduce((n,m)=>n+m.displayPoints,0)));stat('坐标单位',DATA.unit);const dim=subtract(bounds.max,bounds.min);for(let j=0;j<3;j++)stat('XYZ'[j]+' 方向跨度',format(dim[j])+' '+DATA.unit);const filtered=current.reduce((n,m)=>n+m.nonfiniteRemoved,0);if(filtered)stat('排除非有限点',format(filtered));$('title').textContent=current.length===1?current[0].label:'共同坐标系 · 叠加审阅';$('sizeLegend').textContent='坐标跨度 XYZ '+dim.map(format).join(' × ')+' '+DATA.unit;$('legend').replaceChildren();$('paths').replaceChildren();for(const m of current){const row=document.createElement('div');row.className='legend-row';const d=document.createElement('span');d.className='dot';d.style.background='rgb('+m.palette.map(v=>Math.round(v*255)).join(',')+')';const t=document.createElement('span');t.textContent=m.label;row.append(d,t);$('legend').appendChild(row);const p=document.createElement('div');p.textContent=m.label+' · '+(m.hasColors?'包含顶点颜色':'无顶点颜色，预览沿 Z 着色')+'\n'+m.path;p.style.whiteSpace='pre-wrap';p.style.marginBottom='9px';$('paths').appendChild(p);}dirty=true;}
function attributes(position,color){gl.bindBuffer(gl.ARRAY_BUFFER,position);gl.enableVertexAttribArray(loc.p);gl.vertexAttribPointer(loc.p,3,gl.FLOAT,false,0,0);gl.bindBuffer(gl.ARRAY_BUFFER,color);gl.enableVertexAttribArray(loc.c);gl.vertexAttribPointer(loc.c,3,gl.UNSIGNED_BYTE,true,0,0);}
function render(){requestAnimationFrame(render);const ratio=Math.min(window.devicePixelRatio||1,2),w=Math.max(1,Math.floor(canvas.clientWidth*ratio)),h=Math.max(1,Math.floor(canvas.clientHeight*ratio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;dirty=true;}if(!dirty)return;dirty=false;gl.viewport(0,0,w,h);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);const offset=viewDirection().map(v=>v*distance),eye=target.map((v,i)=>v+offset[i]),z=normalized(subtract(eye,target)),x=normalized(cross(upVector(),z)),y=cross(z,x);const view=new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);const projection=perspective(w/h,Math.max(radius*.0005,distance-radius*2)*.5,distance+radius*8);gl.uniformMatrix4fv(loc.mvp,false,multiply(projection,view));gl.uniform1f(loc.size,Number($('pointSize').value)*ratio);gl.uniform1f(loc.isPoint,1);const overlay=$('model').value==='all';for(const m of selected()){attributes(m.positionBuffer,m.colorBuffer);gl.uniform1f(loc.tintMode,$('color').value==='model'||overlay?1:0);gl.uniform3fv(loc.tint,m.palette);gl.drawArrays(gl.POINTS,0,m.displayPoints);}if($('axes').checked){attributes(axisPosition,axisColor);gl.uniform1f(loc.tintMode,0);gl.uniform1f(loc.isPoint,0);gl.drawArrays(gl.LINES,0,6);}$('viewStatus').textContent='观察距离 '+format(distance)+' '+DATA.unit;}
$('model').addEventListener('change',()=>fit());$('reset').onclick=()=>fit();$('front').onclick=()=>{fit(false);yaw=upAxis==='z'?-Math.PI/2:0;pitch=0;dirty=true;};$('top').onclick=()=>{fit(false);yaw=-Math.PI/2;pitch=Math.PI/2-.005;dirty=true;};$('color').onchange=$('axes').onchange=()=>{dirty=true;};$('pointSize').oninput=()=>{$('pointSizeValue').textContent=Number($('pointSize').value).toFixed(1);dirty=true;};
let drag=null;canvas.addEventListener('contextmenu',e=>e.preventDefault());canvas.addEventListener('pointerdown',e=>{drag={id:e.pointerId,x:e.clientX,y:e.clientY,pan:e.shiftKey||e.button!==0};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.pan||e.shiftKey){const z=viewDirection(),right=normalized(cross(upVector(),z)),up=cross(z,right),scale=distance*.93/Math.max(canvas.clientHeight,1);target=target.map((v,i)=>v-right[i]*dx*scale+up[i]*dy*scale);}else{yaw-=dx*.008;pitch=Math.max(-1.565,Math.min(1.565,pitch+dy*.008));}dirty=true;});for(const name of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(name,()=>{drag=null;});canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.min(radius*100,Math.max(radius*.03,distance*Math.exp(Math.max(-100,Math.min(100,e.deltaY))*.003)));dirty=true;},{passive:false});
fit();requestAnimationFrame(render);
</script></body></html>'''


def load_cloud(specification, limit, o3d):
    label, separator, raw_path = specification.partition("=")
    if not separator or not label.strip() or not raw_path:
        raise ValueError("Each --cloud must be 'label=path.ply'")
    path = Path(raw_path).resolve()
    if path.suffix.lower() != ".ply" or not path.is_file():
        raise ValueError(f"Missing PLY input: {path}")
    cloud = _read_ply_cloud(o3d, path)
    points = np.asarray(cloud.points)
    original_count = len(points)
    valid = np.isfinite(points).all(axis=1)
    points = points[valid]
    if not len(points):
        raise ValueError(f"No finite points in {path}")
    minimum, maximum = points.min(axis=0), points.max(axis=0)
    indices = np.linspace(0, len(points) - 1, min(limit, len(points)), dtype=np.int64)
    positions = points[indices].astype("<f4")
    if not np.isfinite(positions).all():
        raise ValueError(f"Coordinates cannot be represented as float32 for WebGL: {path}")
    has_colors = cloud.has_colors()
    if has_colors:
        colors = np.asarray(cloud.colors)[valid][indices]
        if not np.isfinite(colors).all():
            raise ValueError(f"Nonfinite vertex colors in {path}")
        rgb = np.rint(np.clip(colors, 0, 1) * 255).astype(np.uint8)
    else:
        height = (positions[:, 2] - minimum[2]) / max(maximum[2] - minimum[2], 1e-12)
        low, high = np.array([65, 122, 200]), np.array([210, 236, 247])
        rgb = np.rint(low + np.clip(height[:, None], 0, 1) * (high - low)).astype(np.uint8)
    with path.open("rb") as stream:
        sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"label": label.strip(), "path": str(path), "sourceSha256": sha256,
            "originalPoints": original_count, "displayPoints": len(positions),
            "nonfiniteRemoved": original_count - len(points), "hasColors": has_colors,
            "bounds": {"min": minimum.tolist(), "max": maximum.tolist()},
            "xyz": base64.b64encode(positions.tobytes()).decode("ascii"),
            "rgb": base64.b64encode(rgb.tobytes()).decode("ascii")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloud", action="append", required=True, help="Repeat 'label=path.ply'")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unit", choices=("mm", "m"), required=True,
                        help="Established coordinate unit shared by the supplied files; no rescaling")
    parser.add_argument("--max-points", type=int, default=40_000, help="Display cap per cloud, at most 40000")
    parser.add_argument("--allow-overlay", action="store_true", help="Enable overlay only for already registered inputs")
    parser.add_argument("--up-axis", choices=("x", "y", "z"), default="z", help="Initial view up axis; source coordinates are unchanged")
    parser.add_argument("--invert-up", action="store_true", help="Use the negative selected axis for view up; does not transform geometry")
    parser.add_argument("--provenance", default="本地 PLY 文件；处理来源以对象标签和随附报告为准。")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    if not 1 <= args.max_points <= 40_000:
        parser.error("--max-points must be between 1 and 40000")
    if args.out.suffix.lower() != ".html":
        parser.error("--out must have .html extension")
    o3d = require_open3d()
    clouds = [load_cloud(specification, args.max_points, o3d) for specification in args.cloud]
    payload = {"clouds": clouds, "unit": args.unit, "allowOverlay": args.allow_overlay, "upAxis": args.up_axis, "invertUp": args.invert_up,
               "notes": args.notes, "provenance": args.provenance,
               "sampling": "deterministic equally spaced source indices after finite-point filtering"}
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HTML.replace("__PAYLOAD__", encoded, 1), encoding="utf-8")
    print(json.dumps({"output": str(output), "bytes": output.stat().st_size,
                      "clouds": [{"label": m["label"], "original_points": m["originalPoints"],
                                  "display_points": m["displayPoints"]} for m in clouds],
                      "overlay_enabled": args.allow_overlay}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
