"""Embed precomputed same-coordinate fusion comparisons in an offline HTML page.

This renderer does not compute registration or nearest neighbours. Distances
and nearest-point coordinates are supplied by the analysis JSON and refer to
its full analysis clouds, not the smaller display samples.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import numpy as np


HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:;">
<title>融合结果 · 空间差异审阅</title><style>
:root{font-family:system-ui,"Microsoft YaHei",sans-serif;color-scheme:dark;color:#e5edf7;background:#0b111c}*{box-sizing:border-box}body{margin:0;display:flex;flex-direction:column;height:100vh;overflow:hidden}header{height:67px;flex:none;padding:12px 20px;background:#111c2a;border-bottom:1px solid #2d3c50;display:flex;align-items:center;justify-content:space-between}h1{font-size:18px;margin:0 0 4px;letter-spacing:.04em}.subtitle{color:#9aafc7;font-size:12px}.offline{border:1px solid #315c50;color:#8bd6b9;font-size:12px;padding:6px 10px;border-radius:16px}main{flex:1;display:flex;min-height:0}aside{width:340px;flex:none;padding:17px;overflow:auto;background:#111a27;border-right:1px solid #2b394b}label,.label{display:block;font-size:12px;color:#a6b9cf;margin-bottom:7px}.field{margin-bottom:17px}select,button{font:inherit;font-size:13px;background:#1b2b40;color:#edf5ff;border:1px solid #3a5069;border-radius:6px;padding:8px 9px}select{width:100%;cursor:pointer}button{cursor:pointer}button:hover{background:#284562}.bar{display:flex;gap:5px}.bar button{flex:1}.bar button.active{background:#376893;border-color:#83b8e8}.layers{border:0;padding:0;margin:0}.check{display:flex;align-items:center;gap:7px;color:#d4e0ee;margin:9px 0;font-size:12px;line-height:1.5}.check input{accent-color:#8fbcf0}.swatch{width:9px;height:9px;border-radius:50%;flex:none}.green{background:#67d391}.blue{background:#54a8ff}.orange{background:#ffad5c}.box{border-top:1px solid #2b3b50;padding-top:14px;margin-top:15px}.small{font-size:12px;color:#a6bad0;line-height:1.7}.note{white-space:pre-wrap}.hint{font-size:11px;line-height:1.7;color:#93abc4}.notice{font-size:12px;line-height:1.7;background:#292a22;border:1px solid #4a4932;border-radius:6px;color:#ded39e;padding:9px}.metric{display:flex;justify-content:space-between;gap:12px;font-size:12px;margin:9px 0}.metric span:first-child{color:#adc0d7}.metric strong{font-variant-numeric:tabular-nums;font-weight:550}.support{background:#192c32;border-radius:7px;padding:8px 10px;margin:9px 0}.support-title{font-size:11px;color:#adc6ce}.support-value{font-size:21px;color:#77dfb0;margin:3px 0}.support-detail{font-size:11px;color:#a8bacd}.row{display:flex;gap:8px}.row>.support{flex:1}.mono{font:11px/1.8 ui-monospace,Consolas,monospace;word-break:break-all;color:#b5c7dc}.point-label{color:#b4c7da;font-size:11px;margin:9px 0 3px}.path{font-size:10px;line-height:1.7;color:#849cb8;word-break:break-all}.source-title{font-size:12px;margin:10px 0 4px;color:#d8e4f4}details summary{cursor:pointer;color:#b4c8e0;font-size:12px}.controls{display:flex;gap:6px;flex-wrap:wrap}input[type=range]{width:100%;accent-color:#83b8ec}#viewport{position:relative;flex:1;min-width:0;background:radial-gradient(ellipse at 50% 45%,#1c2d40,#0b111c 78%)}canvas{display:block;width:100%;height:100%;touch-action:none;outline:none}.viewlabel{position:absolute;top:19px;font-size:13px;color:#d3e2f5;pointer-events:none;max-width:45%}#leftTitle{left:19px}#rightTitle{left:calc(50% + 19px);display:none}#divider{display:none;position:absolute;left:50%;top:0;bottom:0;border-left:1px solid #52657c;pointer-events:none}#hud{position:absolute;bottom:16px;left:18px;right:18px;font-size:11px;color:#92a8c2;pointer-events:none;display:flex;justify-content:space-between;gap:15px}#error{display:none;position:absolute;inset:25% 10%;padding:20px;border:1px solid #a9636c;border-radius:9px;background:#311f29;line-height:1.8}#pickedBadge{position:absolute;right:18px;top:55px;display:none;border:1px solid #6f785a;background:#202921cc;padding:7px 10px;color:#e3dfab;font-size:11px;pointer-events:none}fieldset:disabled{opacity:.5}@media(max-width:760px){aside{width:280px;padding:12px}header{padding:10px 13px}h1{font-size:16px}.subtitle{font-size:10px}.offline{display:none}#hud{font-size:9px}}
</style></head><body><header><div><h1>融合结果 · 空间差异审阅</h1><div id="subtitle" class="subtitle">同一扫描坐标系 · 双向空间支持 · 点击点查看对应关系</div></div><span class="offline">独立离线 HTML · 无网络请求</span></header>
<main><aside>
<div class="field"><label for="pair">对比案例</label><select id="pair"></select></div>
<div class="field"><label for="mode">查看方式</label><select id="mode"><option value="classification">三色差异叠加</option><option value="side">左右同步对照</option><option value="own">仅本项目结果</option><option value="official">仅官方结果</option></select></div>
<div class="field"><label>空间容差（毫米）</label><div id="thresholds" class="bar"></div></div>
<fieldset class="layers" id="layers"><label class="check"><input id="common" type="checkbox" checked><span id="swatchCommon" class="swatch green"></span>双方邻域支持（距离 ≤ 容差）</label><label class="check"><input id="onlyOwn" type="checkbox" checked><span id="swatchOwn" class="swatch blue"></span>仅本项目支持</label><label class="check"><input id="onlyOfficial" type="checkbox" checked><span id="swatchOfficial" class="swatch orange"></span>仅官方支持</label></fieldset>
<div id="supportHint" class="hint">绿色表示能在对侧找到足够近的点，不表示点逐一相等。蓝色与橙色表示对侧在当前容差内无支持，也可能来自采样密度、遮挡或坐标误差，不直接代表孔洞或优劣。</div>
<div class="row"><div class="support"><div class="support-title">本项目 → 官方</div><div id="ownFraction" class="support-value">—</div><div id="ownDetail" class="support-detail"></div></div><div class="support"><div class="support-title">官方 → 本项目</div><div id="officialFraction" class="support-value">—</div><div id="officialDetail" class="support-detail"></div></div></div>
<div id="metrics"></div><div id="sampling" class="hint"></div>
<div class="box"><label>视图控制</label><div class="controls"><button id="fit">适配全部</button><button id="front">正视 XY</button><button id="top">俯视 XZ</button></div><label style="margin-top:12px" for="pointSize">点大小 <span id="pointSizeValue">2.0</span></label><input id="pointSize" type="range" min="1" max="6" value="2" step=".1"><label class="check"><input id="showLine" type="checkbox" checked>选点时连接对侧最近位置</label></div>
<div class="box"><label>选点信息</label><div id="picked"><div class="small">点击点云中的一个点。白色为选点，黄色为对侧最近支持位置。</div></div><button id="focus" style="margin-top:12px" disabled>以选点为中心 · 局部放大</button></div>
<div class="box"><div id="caseNotice" class="notice"></div><div id="notes" class="small note" style="margin-top:10px"></div></div>
<details class="box"><summary>数据来源与坐标说明</summary><div id="sources"></div></details>
</aside><section id="viewport"><canvas id="canvas" tabindex="0" aria-label="融合差异的三维交互视图"></canvas><div id="divider"></div><div id="leftTitle" class="viewlabel"></div><div id="rightTitle" class="viewlabel"></div><div id="pickedBadge">白：所选点　黄：对侧最近位置</div><div id="hud"><span>拖动旋转 · Shift / 右键拖动平移 · 滚轮缩放 · 单击选点</span><span id="viewStatus"></span></div><div id="error"></div></section></main>
<script id="comparison-data" type="application/json">__PAYLOAD__</script><script>
'use strict';
const DATA=JSON.parse(document.getElementById('comparison-data').textContent),$=id=>document.getElementById(id),canvas=$('canvas');
const palette=DATA.palette||{common:[103,211,145],own_only:[84,168,255],official_only:[255,173,92]};
const colorOwn=palette.own_only.map(v=>v/255),colorOfficial=palette.official_only.map(v=>v/255),colorCommon=palette.common.map(v=>v/255);
for(const [id,key] of [['swatchCommon','common'],['swatchOwn','own_only'],['swatchOfficial','official_only']])$(id).style.background='rgb('+palette[key].join(',')+')';
const pairs=DATA.pairs;let pairIndex=Math.max(0,pairs.findIndex(p=>p.id===DATA.initialPair)),threshold=DATA.initialThreshold,selection=null,dirty=true,lastViews=[];
for(let i=0;i<pairs.length;i++){const option=document.createElement('option');option.value=String(i);option.textContent=pairs[i].label;$('pair').appendChild(option);}$('pair').value=String(pairIndex);
function pair(){return pairs[pairIndex];}function isMesh(){return pair().metadata.distanceMethod==='triangle_surface'||String(pair().metadata.kind||'').includes('mesh_surface');}function mode(){return $('mode').value;}function classified(){return mode()==='classification'||mode()==='side';}
function f(n,digits=2){return Number(n).toLocaleString('zh-CN',{maximumFractionDigits:digits});}function vector(v){return Array.from(v).map(n=>f(n,3)).join(' , ');}
function decode64(text,type='f32'){const binary=atob(text),bytes=new Uint8Array(binary.length);for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);const width=type==='f64'?8:4,result=type==='f64'?new Float64Array(bytes.length/8):new Float32Array(bytes.length/4),view=new DataView(bytes.buffer);for(let i=0;i<result.length;i++)result[i]=type==='f64'?view.getFloat64(i*8,true):view.getFloat32(i*4,true);return result;}
function fatal(text){$('error').textContent=text;$('error').style.display='block';}
const gl=canvas.getContext('webgl',{antialias:true,alpha:true});if(!gl){fatal('当前浏览器无法创建 WebGL 画布，请在启用硬件加速的浏览器中打开这个本地 HTML 文件。');throw Error('WebGL unavailable');}
function compile(type,text){const shader=gl.createShader(type);gl.shaderSource(shader,text);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(shader));return shader;}
// Keep position arithmetic highp, but explicitly match cross-stage precision.
// Vertex floats default to highp; fragment floats below default to mediump.
const vertexShaderSource=`
precision highp float;
attribute vec3 aPosition;
attribute float aClass;
uniform mat4 uMVP;
uniform float uPointSize;
uniform float uSource;
uniform mediump float uClassify;
uniform mediump float uOverride;
uniform vec3 uOverrideColor;
uniform vec3 uColorCommon;
uniform vec3 uColorOwn;
uniform vec3 uColorOfficial;
varying mediump vec3 vColor;
varying mediump float vClass;
void main(){gl_Position=uMVP*vec4(aPosition,1.0);gl_PointSize=uPointSize;vClass=aClass;vec3 c=vClass<.5?uColorCommon:(vClass<1.5?uColorOwn:uColorOfficial);if(uClassify<.5)c=uSource<.5?uColorOwn:uColorOfficial;vColor=mix(c,uOverrideColor,uOverride);}`;
const fragmentShaderSource=`
precision mediump float;
uniform float uIsPoint;
uniform mediump float uClassify;
uniform mediump float uOverride;
uniform vec3 uVisible;
varying mediump vec3 vColor;
varying mediump float vClass;
void main(){if(uIsPoint>.5&&length(gl_PointCoord-vec2(.5))>.5)discard;if(uClassify>.5&&uOverride<.5){if(vClass<.5&&uVisible.x<.5)discard;if(vClass>=.5&&vClass<1.5&&uVisible.y<.5)discard;if(vClass>=1.5&&uVisible.z<.5)discard;}gl_FragColor=vec4(vColor,1.0);}`;
let program;try{program=gl.createProgram();gl.attachShader(program,compile(gl.VERTEX_SHADER,vertexShaderSource));gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragmentShaderSource));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));}catch(error){fatal('三维着色器初始化失败：'+error.message);throw error;}
gl.useProgram(program);gl.enable(gl.DEPTH_TEST);gl.clearColor(0,0,0,0);
const loc={position:gl.getAttribLocation(program,'aPosition'),classValue:gl.getAttribLocation(program,'aClass')};for(const name of ['MVP','PointSize','Source','Classify','Override','OverrideColor','IsPoint','Visible','ColorCommon','ColorOwn','ColorOfficial'])loc[name]=gl.getUniformLocation(program,'u'+name);
gl.uniform3fv(loc.ColorCommon,colorCommon);gl.uniform3fv(loc.ColorOwn,colorOwn);gl.uniform3fv(loc.ColorOfficial,colorOfficial);
function upload(array){const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,array,gl.STATIC_DRAW);return buffer;}
for(const p of pairs)for(const key of ['own','official']){const source=p[key];source.points=decode64(source.xyz);source.distanceValues=decode64(source.distances,'f64');source.nearestPoints=decode64(source.nearest);source.positionsBuffer=upload(source.points);source.classValues=new Float32Array(source.displayCount);source.classBuffer=upload(source.classValues);delete source.xyz;delete source.distances;delete source.nearest;}
const highlightBuffer=gl.createBuffer();
function subtract(a,b){return a.map((v,i)=>v-b[i]);}function dot(a,b){return a.reduce((s,v,i)=>s+v*b[i],0);}function cross(a,b){return[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];}function normalize(v){const n=Math.hypot(...v);return v.map(x=>x/n);}
function multiply(a,b){const result=new Float32Array(16);for(let c=0;c<4;c++)for(let r=0;r<4;r++)for(let k=0;k<4;k++)result[c*4+r]+=a[k*4+r]*b[c*4+k];return result;}
function perspective(aspect,near,far){const scale=1/Math.tan(Math.PI/7.2),nf=1/(near-far);return new Float32Array([scale/aspect,0,0,0,0,scale,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0]);}
let yaw=.4,pitch=.2,distance=1,radius=1,target=[0,0,0];function direction(){return[Math.sin(yaw)*Math.cos(pitch),Math.sin(pitch),Math.cos(yaw)*Math.cos(pitch)];}
function fit(reset=true){const b=pair().bounds;target=b.min.map((v,i)=>(v+b.max[i])/2);radius=Math.max(Math.hypot(...subtract(b.max,b.min))/2,1e-6);const aspect=canvas.clientWidth/(mode()==='side'?2:1)/Math.max(canvas.clientHeight,1);distance=radius*2.9*Math.max(1,1/aspect);if(reset){yaw=.4;pitch=.2;}dirty=true;}
function metric(label,value){const row=document.createElement('div');row.className='metric';const a=document.createElement('span'),b=document.createElement('strong');a.textContent=label;b.textContent=value;row.append(a,b);$('metrics').appendChild(row);}
function metadataText(value){if(value==null)return '';return typeof value==='string'?value:JSON.stringify(value,null,2);}
function updateClasses(){for(const key of ['own','official']){const s=pair()[key];if(s.classThreshold===threshold)continue;for(let i=0;i<s.displayCount;i++)s.classValues[i]=s.distanceValues[i]<=threshold?0:(key==='own'?1:2);gl.bindBuffer(gl.ARRAY_BUFFER,s.classBuffer);gl.bufferData(gl.ARRAY_BUFFER,s.classValues,gl.DYNAMIC_DRAW);s.classThreshold=threshold;}}
function updatePanel(){updateClasses();const p=pair(),stats=p.stats[String(threshold)];$('subtitle').textContent='同一扫描坐标系 · '+(isMesh()?'双向采样点到三角面距离':'双向点云近邻支持')+' · 点击点查看对应关系';$('supportHint').textContent=(isMesh()?'绿色表示到对侧三角表面的最近距离不超过容差。':'绿色表示到对侧完整分析点云能找到足够近的点。')+'这不表示点逐一相等；蓝色与橙色表示对侧在当前容差内无支持，也可能来自密度、遮挡或坐标误差，不直接代表孔洞或优劣。';for(const key of ['own','official']){const s=stats[key];$(key+'Fraction').textContent=f(s.commonFraction*100,1)+'%';$(key+'Detail').textContent=f(s.common)+' / '+f(s.total)+(isMesh()?' 个分析采样点':' 个分析点');}$('metrics').replaceChildren();metric('仅本项目支持',f(stats.own.unique)+' 点（'+f(stats.own.uniqueFraction*100,1)+'%）');metric('仅官方支持',f(stats.official.unique)+' 点（'+f(stats.official.uniqueFraction*100,1)+'%）');metric('本项目 → 官方 中位距离',f(stats.medianOwn,3)+' mm');metric('官方 → 本项目 中位距离',f(stats.medianOfficial,3)+' mm');metric('本项目 / 官方 P90 距离',f(stats.p90Own,3)+' / '+f(stats.p90Official,3)+' mm');$('sampling').textContent=(metadataText(p.metadata.analysisDescription)||(isMesh()?'统计基于完整表面分析采样到对侧三角面的距离。':'统计基于完整分析云（'+f(DATA.voxelMm)+' mm 体素）。'))+' 显示抽样 '+f(p.own.displayCount)+' + '+f(p.official.displayCount)+' 点，显示比例不代表统计比例。';$('caseNotice').textContent=metadataText(p.metadata.fairness)||'仅在同一扫描坐标系下比较空间邻域支持。';$('notes').textContent=metadataText(p.metadata.notes);$('sources').replaceChildren();for(const key of ['own','official']){const s=p[key],head=document.createElement('div'),text=document.createElement('div'),path=document.createElement('div');head.className='source-title';head.textContent=key==='own'?'本项目结果':'官方结果';text.className='small note';text.textContent=s.provenance;path.className='path';path.textContent=s.path;$('sources').append(head,text,path);}const coordinate=document.createElement('div');coordinate.className='small note';coordinate.style.marginTop='10px';coordinate.textContent='坐标：'+metadataText(p.metadata.coordinate);$('sources').appendChild(coordinate);$('layers').disabled=!classified();$('divider').style.display=mode()==='side'?'block':'none';$('rightTitle').style.display=mode()==='side'?'block':'none';$('leftTitle').textContent=mode()==='side'?'本项目结果':mode()==='own'?'本项目结果':mode()==='official'?'官方结果':'绿色：双方支持 · 蓝色：仅本项目 · 橙色：仅官方';$('rightTitle').textContent='官方结果';updatePicked();dirty=true;}
for(const value of DATA.thresholds){const button=document.createElement('button');button.textContent=String(value)+' mm';button.dataset.threshold=String(value);button.onclick=()=>{threshold=value;for(const b of $('thresholds').children)b.classList.toggle('active',Number(b.dataset.threshold)===threshold);updatePanel();};button.classList.toggle('active',value===threshold);$('thresholds').appendChild(button);}
function field(title,text,mono=false){const label=document.createElement('div'),value=document.createElement('div');label.className='point-label';label.textContent=title;value.className=mono?'mono':'small';value.textContent=text;$('picked').append(label,value);}
function selectionVisible(){if(!selection)return false;if(mode()==='own'&&selection.source!=='own'||mode()==='official'&&selection.source!=='official')return false;return visible(pair()[selection.source],selection.index);}
function updatePicked(){if(selection&&!selectionVisible())selection=null;$('picked').replaceChildren();$('focus').disabled=!selection;$('pickedBadge').style.display=selection?'block':'none';if(!selection){field('单击选点',isMesh()?'白色为所选表面采样点；黄色为对侧三角表面的最近位置。':'白色为所选显示点；黄色为对侧完整分析云中的最近点。');return;}const source=pair()[selection.source],i=selection.index,pos=source.points.subarray(i*3,i*3+3),nearest=source.nearestPoints.subarray(i*3,i*3+3),d=source.distanceValues[i];field('点来源',(selection.source==='own'?'本项目结果':'官方结果')+' · 预览索引 '+i);field(isMesh()?'所选表面采样 XYZ（mm）':'选点 XYZ（mm）',vector(pos),true);field(isMesh()?'对侧最近表面位置 XYZ（mm）':'对侧最近分析点 XYZ（mm）',vector(nearest),true);field(isMesh()?'至对侧三角表面的最近距离':'至对侧完整分析云的最近距离',f(d,4)+' mm');field('当前容差下的分类',d<=threshold?'双方邻域支持（≤ '+threshold+' mm）':selection.source==='own'?'仅本项目支持':'仅官方支持');}
function bindCloud(source){gl.bindBuffer(gl.ARRAY_BUFFER,source.positionsBuffer);gl.enableVertexAttribArray(loc.position);gl.vertexAttribPointer(loc.position,3,gl.FLOAT,false,0,0);gl.bindBuffer(gl.ARRAY_BUFFER,source.classBuffer);gl.enableVertexAttribArray(loc.classValue);gl.vertexAttribPointer(loc.classValue,1,gl.FLOAT,false,0,0);}
function drawHighlight(points,primitive,color,size){gl.bindBuffer(gl.ARRAY_BUFFER,highlightBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(points),gl.DYNAMIC_DRAW);gl.enableVertexAttribArray(loc.position);gl.vertexAttribPointer(loc.position,3,gl.FLOAT,false,0,0);gl.disableVertexAttribArray(loc.classValue);gl.vertexAttrib1f(loc.classValue,0);gl.uniform1f(loc.Override,1);gl.uniform3fv(loc.OverrideColor,color);gl.uniform1f(loc.IsPoint,primitive===gl.POINTS?1:0);gl.uniform1f(loc.PointSize,size);gl.drawArrays(primitive,0,points.length/3);}
function render(){requestAnimationFrame(render);const ratio=Math.min(window.devicePixelRatio||1,2),width=Math.max(1,Math.round(canvas.clientWidth*ratio)),height=Math.max(1,Math.round(canvas.clientHeight*ratio));if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;fit(false);dirty=true;}if(!dirty)return;dirty=false;gl.disable(gl.SCISSOR_TEST);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);const eye=target.map((v,i)=>v+direction()[i]*distance),z=normalize(subtract(eye,target)),x=normalize(cross([0,1,0],z)),y=cross(z,x),view=new Float32Array([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);const configs=mode()==='side'?[{keys:['own'],x:0,width:canvas.clientWidth/2},{keys:['official'],x:canvas.clientWidth/2,width:canvas.clientWidth/2}]:[{keys:mode()==='own'?['own']:mode()==='official'?['official']:['own','official'],x:0,width:canvas.clientWidth}];lastViews=[];for(const config of configs){const mvp=multiply(perspective(config.width/Math.max(canvas.clientHeight,1),Math.max(radius*.0005,distance-radius*2)*.5,distance+radius*8),view);lastViews.push({...config,height:canvas.clientHeight,mvp});const pixelStart=Math.round(config.x*ratio),pixelEnd=Math.round((config.x+config.width)*ratio);gl.viewport(pixelStart,0,pixelEnd-pixelStart,height);gl.enable(gl.SCISSOR_TEST);gl.scissor(pixelStart,0,pixelEnd-pixelStart,height);gl.uniformMatrix4fv(loc.MVP,false,mvp);gl.uniform1f(loc.Classify,classified()?1:0);gl.uniform3f(loc.Visible,$('common').checked?1:0,$('onlyOwn').checked?1:0,$('onlyOfficial').checked?1:0);gl.uniform1f(loc.Override,0);gl.uniform1f(loc.IsPoint,1);gl.uniform1f(loc.PointSize,Number($('pointSize').value)*ratio);for(const key of config.keys){const source=pair()[key];bindCloud(source);gl.uniform1f(loc.Source,key==='own'?0:1);gl.drawArrays(gl.POINTS,0,source.displayCount);}if(selection&&selectionVisible()){const s=pair()[selection.source],i=selection.index,p=Array.from(s.points.subarray(i*3,i*3+3)),n=Array.from(s.nearestPoints.subarray(i*3,i*3+3));gl.disable(gl.DEPTH_TEST);if($('showLine').checked)drawHighlight([...p,...n],gl.LINES,[.95,.92,.58],1);if(config.keys.includes(selection.source))drawHighlight(p,gl.POINTS,[1,1,1],8*ratio);if(config.keys.includes(selection.source==='own'?'official':'own'))drawHighlight(n,gl.POINTS,[1,.87,.26],8*ratio);gl.enable(gl.DEPTH_TEST);}}$('viewStatus').textContent='容差 '+threshold+' mm · 两侧坐标共享同一视角';}
function visible(source,index){if(!classified())return true;const d=source.distanceValues[index];return d<=threshold?$('common').checked:source===pair().own?$('onlyOwn').checked:$('onlyOfficial').checked;}
function pick(clientX,clientY){const rect=canvas.getBoundingClientRect(),px=clientX-rect.left,py=clientY-rect.top,v=lastViews.find(c=>px>=c.x&&px<c.x+c.width);if(!v||py<0||py>v.height)return;const m=v.mvp;let best=null;for(const key of v.keys){const source=pair()[key],points=source.points;for(let i=0;i<source.displayCount;i++){if(!visible(source,i))continue;const x=points[3*i],y=points[3*i+1],z=points[3*i+2],w=m[3]*x+m[7]*y+m[11]*z+m[15];if(w<=0)continue;const nx=(m[0]*x+m[4]*y+m[8]*z+m[12])/w,ny=(m[1]*x+m[5]*y+m[9]*z+m[13])/w,nz=(m[2]*x+m[6]*y+m[10]*z+m[14])/w;if(nz< -1||nz>1)continue;const sx=v.x+(nx+1)*v.width/2,sy=(1-ny)*v.height/2,d2=(sx-px)**2+(sy-py)**2;if(d2>81)continue;const score=d2+Math.max(0,nz+1)*5;if(!best||score<best.score)best={source:key,index:i,score};}}selection=best?{source:best.source,index:best.index}:null;updatePicked();dirty=true;}
$('pair').onchange=()=>{pairIndex=Number($('pair').value);selection=null;fit();updatePanel();};$('mode').onchange=()=>{fit(false);updatePanel();dirty=true;};$('fit').onclick=()=>fit();$('focus').onclick=()=>{if(!selection)return;const s=pair()[selection.source];target=Array.from(s.points.subarray(selection.index*3,selection.index*3+3));distance=18*2.9;dirty=true;};$('front').onclick=()=>{fit(false);yaw=0;pitch=0;dirty=true;};$('top').onclick=()=>{fit(false);yaw=0;pitch=Math.PI/2-.005;dirty=true;};for(const id of ['common','onlyOwn','onlyOfficial','showLine'])$(id).onchange=()=>{updatePicked();dirty=true;};$('pointSize').oninput=()=>{$('pointSizeValue').textContent=Number($('pointSize').value).toFixed(1);dirty=true;};
let drag=null;canvas.addEventListener('contextmenu',e=>e.preventDefault());canvas.addEventListener('pointerdown',e=>{drag={id:e.pointerId,x:e.clientX,y:e.clientY,movement:0,pan:e.shiftKey||e.button!==0};canvas.setPointerCapture(e.pointerId);});canvas.addEventListener('pointermove',e=>{if(!drag||drag.id!==e.pointerId)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;drag.movement+=Math.hypot(dx,dy);if(drag.pan||e.shiftKey){const z=direction(),right=normalize(cross([0,1,0],z)),up=cross(z,right),scale=distance*.93/Math.max(canvas.clientHeight,1);target=target.map((v,i)=>v-right[i]*dx*scale+up[i]*dy*scale);}else{yaw-=dx*.008;pitch=Math.max(-1.565,Math.min(1.565,pitch+dy*.008));}dirty=true;});canvas.addEventListener('pointerup',e=>{if(drag&&drag.id===e.pointerId&&drag.movement<4&&e.button===0)pick(e.clientX,e.clientY);drag=null;});for(const event of ['pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;});canvas.addEventListener('wheel',e=>{e.preventDefault();distance=Math.min(radius*100,Math.max(radius*.03,distance*Math.exp(Math.max(-100,Math.min(100,e.deltaY))*.003)));dirty=true;},{passive:false});fit();updatePanel();requestAnimationFrame(render);
</script></body></html>'''


def validate_source(source, name):
    count = source["displayCount"]
    if not isinstance(count, int) or isinstance(count, bool) or not 0 < count <= 200_000:
        raise ValueError(f"Invalid displayCount for {name}")
    arrays = {}
    if source.get("distanceEncoding") != "float64-le":
        raise ValueError(f"Distances must explicitly use float64-le for {name}")
    for field, width in (("xyz", 3), ("distances", 1), ("nearest", 3)):
        raw = base64.b64decode(source[field], validate=True)
        itemsize = 8 if field == "distances" else 4
        if len(raw) != count * width * itemsize:
            raise ValueError(f"Wrong encoded {field} length for {name}")
        values = np.frombuffer(raw, "<f8" if field == "distances" else "<f4")
        if not np.isfinite(values).all():
            raise ValueError(f"Nonfinite {field} for {name}")
        arrays[field] = values
    if np.any(arrays["distances"] < 0):
        raise ValueError(f"Negative nearest distances for {name}")
    if source["analysisCount"] < count:
        raise ValueError(f"Analysis count below display count for {name}")
    for field in ("path", "provenance"):
        if not isinstance(source[field], str):
            raise ValueError(f"Invalid {field} for {name}")


def validate(data):
    if data["unit"] != "mm":
        raise ValueError("Comparison inputs must explicitly use millimetres")
    if not data["pairs"] or not data["thresholds"]:
        raise ValueError("At least one pair and threshold is required")
    if not np.isfinite(data["voxelMm"]) or data["voxelMm"] <= 0:
        raise ValueError("voxelMm must be positive and finite")
    ids = set()
    for pair in data["pairs"]:
        if pair["id"] in ids:
            raise ValueError("Duplicate pair ID")
        ids.add(pair["id"])
        if not isinstance(pair["label"], str) or not isinstance(pair["metadata"], dict):
            raise ValueError("Invalid pair label or metadata")
        bounds = pair["bounds"]
        minimum, maximum = np.array(bounds["min"]), np.array(bounds["max"])
        if minimum.shape != (3,) or maximum.shape != (3,) or not np.isfinite([minimum, maximum]).all() or np.any(minimum > maximum):
            raise ValueError("Invalid comparison bounds")
        for name in ("own", "official"):
            validate_source(pair[name], pair["id"] + "/" + name)
        for threshold in data["thresholds"]:
            if not np.isfinite(threshold) or threshold <= 0:
                raise ValueError("Thresholds must be positive and finite")
            stats = pair["stats"][format(float(threshold), "g")]
            for name in ("own", "official"):
                row = stats[name]
                if row["total"] != pair[name]["analysisCount"] or row["common"] + row["unique"] != row["total"]:
                    raise ValueError("Inconsistent full-analysis counts")
                for field in ("commonFraction", "uniqueFraction"):
                    if not np.isfinite(row[field]) or not 0 <= row[field] <= 1:
                        raise ValueError("Invalid full-analysis fraction")
            if not np.isfinite([stats[k] for k in ("medianOwn", "medianOfficial", "p90Own", "p90Official")]).all():
                raise ValueError("Invalid full-analysis distances")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--initial-pair", default=None)
    parser.add_argument("--threshold", type=float, default=1)
    args = parser.parse_args()
    if args.out.suffix.lower() != ".html":
        parser.error("--out must have an .html extension")
    data = json.loads(args.data.read_text(encoding="utf-8"))
    validate(data)
    if args.threshold not in data["thresholds"]:
        parser.error("Initial threshold must be one of the supplied analysis thresholds")
    initial = args.initial_pair or data.get("initialPair", "scan_04_mesh_baseline")
    available = {pair["id"] for pair in data["pairs"]}
    if initial not in available:
        if args.initial_pair:
            parser.error("Requested initial pair is absent from the analysis data")
        initial = data["pairs"][0]["id"]
    data["initialPair"] = initial
    data["initialThreshold"] = args.threshold
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    encoded = encoded.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HTML.replace("__PAYLOAD__", encoded, 1), encoding="utf-8")
    print(json.dumps({"output": str(output), "bytes": output.stat().st_size,
                      "pairs": len(data["pairs"]), "initial_pair": data["initialPair"],
                      "unit": data["unit"]}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
