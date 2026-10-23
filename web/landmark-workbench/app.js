(function() {
  'use strict';
  try {
  if(document.getElementById('alignment-data').textContent.trim()==='__DATA__'){
    document.getElementById('status').textContent='这是开发模板，没有内嵌模型。请运行 scripts/start-web-studio.ps1，然后在 http://127.0.0.1:8877 选择项目；或打开 reports 中已生成的 workbench.html。';
    return;
  }
  const DATA=JSON.parse(document.getElementById('alignment-data').textContent),M=RegistrationMath,$=id=>document.getElementById(id);
  const state={pairs:[],pending:null,matrix:M.identity(),kind:'existing_candidate',fit:null,label:'',dirty:true,revision:0};
  const clone=value=>JSON.parse(JSON.stringify(value));
  function decode(text,type){const raw=atob(text),bytes=Uint8Array.from(raw,x=>x.charCodeAt(0)),view=new DataView(bytes.buffer);if(type==='u8')return bytes;return type==='u32'?Uint32Array.from({length:bytes.length/4},(_,i)=>view.getUint32(i*4,true)):Float32Array.from({length:bytes.length/4},(_,i)=>view.getFloat32(i*4,true));}
  const models=DATA.clouds.map(row=>({...row,points:decode(row.xyz,'f32'),colors:decode(row.rgb,'u8'),originalIds:decode(row.ids,'u32')}));
  let displayGain=1.8;
  function displayRGB(model){if(model.displayGain!==displayGain){model.displayRGB=Uint8Array.from(model.colors,c=>Math.min(255,Math.round(c*displayGain)));model.displayGain=displayGain;}return model.displayRGB;}
  const names=['target','source','overlay'];
  const cameras=names.map(()=>({yaw:1.2,pitch:.15,target:[0,0,0],radius:1,distance:3,mvp:null}));
  const sub=(a,b)=>a.map((x,i)=>x-b[i]),dot=(a,b)=>a.reduce((n,x,i)=>n+x*b[i],0),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  const norm=a=>{const length=Math.hypot(...a);return a.map(x=>x/length);};
  function multiply(a,b){const result=new Float32Array(16);for(let col=0;col<4;col++)for(let row=0;row<4;row++)for(let k=0;k<4;k++)result[col*4+row]+=a[k*4+row]*b[col*4+k];return result;}
  const column=matrix=>Float32Array.from({length:16},(_,i)=>matrix[i%4][Math.floor(i/4)]);
  function direction(camera){return [-Math.sin(camera.pitch),Math.cos(camera.yaw)*Math.cos(camera.pitch),Math.sin(camera.yaw)*Math.cos(camera.pitch)];}
  function cameraMatrix(camera,width,height){
    const z=direction(camera),x=norm(cross([-1,0,0],z)),y=cross(z,x),eye=camera.target.map((v,i)=>v+z[i]*camera.distance);
    const view=Float32Array.from([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);
    const near=Math.max(camera.radius*.0005,(camera.distance-camera.radius*2)*.5),far=camera.distance+camera.radius*8,f=1/Math.tan(Math.PI/8),nf=1/(near-far);
    const projection=Float32Array.from([f/(width/height),0,0,0,0,f,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0]);
    return multiply(projection,view);
  }
  function message(text){$('status').textContent=text;}
  function point(model,index){return Array.from(model.points.slice(index*3,index*3+3));}
  function fitCamera(index){
    const minimum=[Infinity,Infinity,Infinity],maximum=[-Infinity,-Infinity,-Infinity];
    const included=index===2?[0,1]:[index];
    for(const cloud of included)for(let i=0;i<models[cloud].displayPoints;i++){
      let p=point(models[cloud],i);if(index===2&&cloud===1)p=M.apply(state.matrix,p);
      for(let j=0;j<3;j++){minimum[j]=Math.min(minimum[j],p[j]);maximum[j]=Math.max(maximum[j],p[j]);}
    }
    const camera=cameras[index],canvas=$(names[index]);camera.target=minimum.map((x,i)=>(x+maximum[i])/2);camera.radius=Math.max(Math.hypot(...sub(maximum,minimum))/2,1e-4);
    camera.distance=camera.radius*2.8*Math.max(1,canvas.clientHeight/Math.max(canvas.clientWidth,1));camera.yaw=1.2;camera.pitch=.15;state.dirty=true;
  }
  function makeRenderer(canvas){
    const gl=canvas.getContext('webgl',{antialias:true});
    if(!gl){const box=canvas.parentElement.querySelector('.error');box.style.display='block';box.textContent='三维显示初始化失败。选点需要支持 WebGL 的浏览器。';return null;}
    function shader(type,text){const s=gl.createShader(type);gl.shaderSource(s,text);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;}
    const vertex='precision highp float;attribute vec3 aPosition;attribute vec3 aColor;uniform mat4 uMvp;uniform float uSize;uniform float uGain;varying highp vec3 vColor;void main(){gl_Position=uMvp*vec4(aPosition,1.0);gl_PointSize=uSize;vColor=aColor*uGain;}';
    const fragment='precision highp float;varying highp vec3 vColor;uniform vec3 uTint;uniform float uTintMix;void main(){if(distance(gl_PointCoord,vec2(0.5))>0.5)discard;gl_FragColor=vec4(mix(vColor,uTint,uTintMix),1.0);}';
    const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));
    gl.useProgram(program);gl.enable(gl.DEPTH_TEST);gl.clearColor(.047,.078,.125,1);
    const loc={p:gl.getAttribLocation(program,'aPosition'),c:gl.getAttribLocation(program,'aColor'),mvp:gl.getUniformLocation(program,'uMvp'),size:gl.getUniformLocation(program,'uSize'),gain:gl.getUniformLocation(program,'uGain'),tint:gl.getUniformLocation(program,'uTint'),mix:gl.getUniformLocation(program,'uTintMix')};
    function buffer(array){const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,array,gl.STATIC_DRAW);return b;}
    const buffers=models.map(model=>({p:buffer(model.points),c:buffer(model.colors)}));
    return function(index,matrix,ratio){
      gl.viewport(0,0,canvas.width,canvas.height);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.uniform1f(loc.size,2.4*ratio);gl.uniform1f(loc.gain,displayGain);
      for(const cloud of index===2?[0,1]:[index]){
        gl.bindBuffer(gl.ARRAY_BUFFER,buffers[cloud].p);gl.enableVertexAttribArray(loc.p);gl.vertexAttribPointer(loc.p,3,gl.FLOAT,false,0,0);
        gl.bindBuffer(gl.ARRAY_BUFFER,buffers[cloud].c);gl.enableVertexAttribArray(loc.c);gl.vertexAttribPointer(loc.c,3,gl.UNSIGNED_BYTE,true,0,0);
        gl.uniformMatrix4fv(loc.mvp,false,index===2&&cloud===1?multiply(matrix,column(state.matrix)):matrix);
        gl.uniform3fv(loc.tint,cloud===0?[.25,.72,1.]:[1.,.65,.28]);gl.uniform1f(loc.mix,index===2&&$('colorMode').value==='separate'?1:0);
        gl.drawArrays(gl.POINTS,0,models[cloud].displayPoints);
      }
    };
  }
  function softwareRenderer(canvas){
    const fallback=document.createElement('canvas');fallback.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1';
    canvas.parentElement.appendChild(fallback);canvas.style.opacity='0';canvas.style.position='relative';canvas.style.zIndex='2';
    const ctx=fallback.getContext('2d');if(!ctx)throw new Error('Canvas 2D 也不可用');
    canvas.parentElement.querySelector('.error').style.display='none';
    return function(index,matrix,ratio){
      fallback.width=canvas.width;fallback.height=canvas.height;
      const clouds=(index===2?[0,1]:[index]).map(cloud=>({points:models[cloud].points,colors:displayRGB(models[cloud]),
        transform:index===2&&cloud===1?state.matrix:null,tint:index===2&&$('colorMode').value==='separate'?(cloud===0?[64,184,255]:[255,166,71]):null}));
      const frame=ctx.createImageData(canvas.width,canvas.height);frame.data.set(PointRaster.rasterize(clouds,matrix,canvas.width,canvas.height,Math.min(3,ratio*1.2)));ctx.putImageData(frame,0,0);
    };
  }
  let software=false;
  const renderers=names.map(name=>{try{const renderer=makeRenderer($(name));if(renderer)return renderer;}catch(error){$('rendererStatus').textContent='WebGL 不可用：'+error.message;}
    software=true;return softwareRenderer($(name));});
  $('rendererStatus').textContent=software?'已自动使用 Canvas 兼容绘制，可旋转、缩放与选点。':'WebGL 点云绘制已初始化。';
  $('compatibility').onclick=()=>{if(software){message('当前已启用兼容绘制；重新加载页面可重试 WebGL。');return;}names.forEach((name,i)=>{renderers[i]=softwareRenderer($(name));});software=true;$('rendererStatus').textContent='Canvas 兼容绘制，可旋转、缩放与选点。';state.dirty=true;};
  function svgElement(name,attributes){const e=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [k,v] of Object.entries(attributes))e.setAttribute(k,String(v));return e;}
  function markers(index,width,height){
    const svg=$(names[index]+'Markers');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.replaceChildren();
    const entries=[];
    state.pairs.forEach((pair,i)=>{if(index!==1)entries.push({xyz:pair.target.xyz,color:'#7ce3b1',label:i+1});if(index!==0)entries.push({xyz:index===2?M.apply(state.matrix,pair.source.xyz):pair.source.xyz,color:'#ffc178',label:i+1});});
    if(state.pending&&index!==1)entries.push({xyz:state.pending.xyz,color:'#ffffff',label:'…'});
    for(const entry of entries){const screen=M.project(entry.xyz,cameras[index].mvp,width,height);if(!screen)continue;svg.appendChild(svgElement('circle',{cx:screen[0],cy:screen[1],r:6,fill:'none',stroke:entry.color,'stroke-width':2}));const t=svgElement('text',{x:screen[0]+9,y:screen[1]-7,fill:entry.color,'font-size':14});t.textContent=entry.label;svg.appendChild(t);}
  }
  function redraw(){
    requestAnimationFrame(redraw);let changed=state.dirty;
    const ratio=Math.min(window.devicePixelRatio||1,2);
    names.forEach(name=>{const canvas=$(name),w=Math.max(1,Math.round(canvas.clientWidth*ratio)),h=Math.max(1,Math.round(canvas.clientHeight*ratio));if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;changed=true;}});
    if(!changed)return;state.dirty=false;
    names.forEach((name,index)=>{const canvas=$(name),w=Math.max(1,canvas.clientWidth),h=Math.max(1,canvas.clientHeight);cameras[index].mvp=cameraMatrix(cameras[index],w,h);if(renderers[index])renderers[index](index,cameras[index].mvp,ratio);markers(index,w,h);});
  }
  function rmsRadius(points){if(!points.length)return 0;const center=[0,1,2].map(j=>points.reduce((sum,p)=>sum+p[j]/points.length,0));return Math.sqrt(points.reduce((sum,p)=>sum+p.reduce((r,v,j)=>r+(v-center[j])**2,0)/points.length,0));}
  const previewRadii=models.map(model=>rmsRadius(Array.from({length:model.displayPoints},(_,i)=>point(model,i))));
  function updatePairs(){
    $('pairs').replaceChildren();state.pairs.forEach((pair,index)=>{const li=document.createElement('li');li.textContent=`固定 #${pair.target.id} ↔ 移动 #${pair.source.id}`+(state.fit?` · ${state.fit.residuals[index].toFixed(3)} mm`:'');const button=document.createElement('button');button.textContent='移除';button.onclick=()=>{state.pairs.splice(index,1);invalidate();};li.appendChild(button);$('pairs').appendChild(li);});
    $('solve').disabled=state.pairs.length<3;$('export').disabled=$('submitStudio').disabled=state.kind==='manual_stale';
    $('metrics').textContent=state.fit?`选点 RMSE ${state.fit.rmse.toFixed(4)} mm\n最大选点残差 ${state.fit.maxResidual.toFixed(4)} mm\n对应点尺度比 ${state.fit.spanRatio.toFixed(4)}（未缩放）`:`${state.pairs.length} 对对应点${state.pending?' · 等待移动片段选点':''}`;
    if(state.pairs.length>=2)$('metrics').textContent+='\n选点覆盖 RMS 半径：'+[['固定','target',0],['移动','source',1]].map(([label,key,i])=>{const radius=rmsRadius(state.pairs.map(p=>p[key].xyz));return label+' '+radius.toFixed(2)+' mm（预览云半径的 '+(previewRadii[i]>0?(100*radius/previewRadii[i]).toFixed(1):'—')+'%）';}).join('；')+'\n覆盖半径描述选点分布；比例受预览范围影响，不是精度或接受门槛。';
    $('previewLabel').textContent=state.kind==='manual_stale'?'选点已变更，待重新计算':state.label;
    state.dirty=true;
  }
  function invalidate(){state.revision++;if(state.kind==='manual_landmarks')state.kind='manual_stale';state.fit=null;updatePairs();}
  function chooseCandidate(){state.revision++;const row=DATA.candidates[Number($('candidate').value)];state.matrix=clone(row.transform);state.kind='existing_candidate';state.label=row.label;state.fit=null;fitCamera(2);updatePairs();message('已预览所选候选。对应点尚未用于修改它，可开始选点。');}
  DATA.candidates.forEach((row,index)=>{const option=document.createElement('option');option.value=index;option.textContent=row.label;$('candidate').appendChild(option);});
  $('candidate').value=String(Math.max(0,DATA.candidates.findIndex(row=>row.label==='direct_best_training')));
  $('candidate').onchange=$('restore').onclick=chooseCandidate;
  $('resetView').onclick=()=>{for(let i=0;i<3;i++)fitCamera(i);};
  $('undoPair').onclick=()=>{if(state.pending)state.pending=null;else state.pairs.pop();invalidate();};
  $('clearPairs').onclick=()=>{state.pending=null;state.pairs=[];invalidate();};
  $('solve').onclick=()=>{try{const fitted=M.solveRigid(state.pairs.map(p=>p.source.xyz),state.pairs.map(p=>p.target.xyz));state.revision++;state.matrix=fitted.matrix;state.fit=fitted;state.kind='manual_landmarks';state.label='对应点刚体对齐';fitCamera(2);updatePairs();message('对齐已预览。检查局部重影和各对残差；选点残差并不代表整个表面精度。');}catch(error){message('暂不能计算：'+error.message);}};
  $('colorMode').onchange=()=>{state.dirty=true;};
  $('gain').oninput=()=>{displayGain=Math.max(1,Math.min(4,Number($('gain').value)));state.dirty=true;};
  names.forEach((name,index)=>{
    const canvas=$(name);let drag=null;
    canvas.addEventListener('contextmenu',event=>event.preventDefault());
    canvas.addEventListener('pointerdown',event=>{
      if((event.altKey||$('pickMode').checked)&&index<2&&event.button===0){
        if(!cameras[index].mvp)return;
        const rect=canvas.getBoundingClientRect(),hit=M.pickPoint(models[index].points,cameras[index].mvp,rect.width,rect.height,event.clientX-rect.left,event.clientY-rect.top,10);
        if(!hit){message('附近没有可选的可见点，请放大后重试。');return;}
        const selected={id:Number(models[index].originalIds[hit.index]),xyz:point(models[index],hit.index)};
        if(index===0){state.pending=selected;message('已选固定点。请在中间移动片段中选择同一位置。');}
        else if(!state.pending){message('先在左侧固定片段选点，再选移动片段。');return;}
        else{if(state.pairs.some(pair=>pair.source.id===selected.id||pair.target.id===state.pending.id)){message('该点已用于已有对应对，请选择另一个位置。');return;}if(state.pairs.length>=64){message('当前最多64对对应点，请先保存或移除部分选点。');return;}state.pairs.push({target:state.pending,source:selected});state.pending=null;message(`已记录 ${state.pairs.length} 对。至少三对且不要集中在一条线上。`);}
        invalidate();return;
      }
      drag={id:event.pointerId,x:event.clientX,y:event.clientY,pan:event.shiftKey||event.button!==0};canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove',event=>{if(!drag||drag.id!==event.pointerId)return;const dx=event.clientX-drag.x,dy=event.clientY-drag.y;drag.x=event.clientX;drag.y=event.clientY;const camera=cameras[index];if(drag.pan||event.shiftKey){const z=direction(camera),right=norm(cross([-1,0,0],z)),up=cross(z,right),scale=camera.distance*.85/Math.max(canvas.clientHeight,1);camera.target=camera.target.map((x,i)=>x-right[i]*dx*scale+up[i]*dy*scale);}else{camera.yaw-=dx*.008;camera.pitch=Math.max(-1.56,Math.min(1.56,camera.pitch+dy*.008));}state.dirty=true;});
    for(const event of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(event,()=>{drag=null;});
    canvas.addEventListener('wheel',event=>{event.preventDefault();const camera=cameras[index];camera.distance=Math.max(camera.radius*.08,Math.min(camera.radius*100,camera.distance*Math.exp(Math.max(-100,Math.min(100,event.deltaY))*.003)));state.dirty=true;},{passive:false});
  });
  // Drafts deliberately contain no fitted matrix. A restored manual preview must be recomputed.
  let draftContext=null,draftBusy=false,draftRefresh=0;
  const server=DATA.serverContext&&window.location?.protocol==='http:'?DATA.serverContext:null;
  function draftRecord(){return {format:'reconstruction-landmark-draft',format_version:1,unit:'mm',
    source:{sha256:models[1].sourceSha256,fragment_id:models[1].fragmentId??1},target:{sha256:models[0].sourceSha256,fragment_id:models[0].fragmentId??0},
    candidate_label:DATA.candidates[Number($('candidate').value)].label,candidate_sha256:DATA.candidateReference.sha256,requires_recompute:state.kind!=='existing_candidate',point_pairs:clone(state.pairs),pending_target:clone(state.pending)};}
  function downloadJSON(record,name){const blob=new Blob([JSON.stringify(record,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function applyDraft(draft){
    if(draft.format!=='reconstruction-landmark-draft'||draft.format_version!==1||draft.unit!=='mm'||typeof draft.requires_recompute!=='boolean'||!Array.isArray(draft.point_pairs)||draft.point_pairs.length>64)throw Error('不支持的草稿格式');
    for(const [key,index] of [['target',0],['source',1]])if(draft[key]?.sha256!==models[index].sourceSha256||draft[key]?.fragment_id!==(models[index].fragmentId??index))throw Error('草稿模型、方向或片段身份不一致');
    if(draft.candidate_sha256!==DATA.candidateReference.sha256)throw Error('草稿候选来源已换版');
    const candidate=DATA.candidates.findIndex(row=>row.label===draft.candidate_label);if(candidate<0)throw Error('草稿候选不在当前工作区');
    const maps=models.map(model=>new Map(Array.from(model.originalIds,(id,index)=>[id,index]))),used=[new Set(),new Set()];
    function selected(value,index,allowDuplicate=false){const id=value?.id,row=maps[index].get(id);if(!Number.isInteger(id)||row===undefined||(!allowDuplicate&&used[index].has(id)))throw Error('选点重复或当前预览不含所需原顶点，请保留原编号重建预览');const xyz=point(models[index],row);if(!Array.isArray(value.xyz)||value.xyz.length!==3||value.xyz.some((v,i)=>v!==xyz[i]))throw Error('草稿坐标与当前原点编号不一致');used[index].add(id);return {id,xyz};}
    const pairs=draft.point_pairs.map(pair=>({target:selected(pair.target,0),source:selected(pair.source,1)})),pending=draft.pending_target===null?null:selected(draft.pending_target,0,true);
    // All validation completes before modifying the current editor.
    $('candidate').value=String(candidate);state.pairs=pairs;state.pending=pending;state.matrix=clone(DATA.candidates[candidate].transform);state.fit=null;state.kind=draft.requires_recompute?'manual_stale':'existing_candidate';state.label=DATA.candidates[candidate].label;state.revision++;
    fitCamera(2);updatePairs();message(draft.requires_recompute?'草稿选点已恢复。当前显示保存候选位置，请重新计算刚体对齐后再导出或提交。':'草稿选点与候选位置已恢复；尚未提交任务。');
  }
  async function draftAPI(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.error||'草稿请求失败');return result;}
  function draftControls(){const available=server&&draftContext?.page_sha256===server.page_sha256;$('saveDraft').disabled=draftBusy||!available;$('refreshDrafts').disabled=draftBusy||!server;$('restoreDraft').disabled=draftBusy||!available||!draftContext?.drafts.some(d=>d.id===$('draftSelect').value&&d.available);}
  function showDrafts(context){draftContext=context;const previous=$('draftSelect').value;$('draftSelect').replaceChildren();for(const row of context.drafts){const option=document.createElement('option');option.value=row.id;option.disabled=!row.available;option.textContent=`${row.label} · ${row.pairs}对${row.pending?'＋待配对':''} · ${row.created_at.slice(0,19).replace('T',' ')} UTC`+(row.available?'':' · '+row.reason);$('draftSelect').appendChild(option);}const chosen=context.drafts.find(d=>d.id===previous&&d.available)||context.drafts.find(d=>d.available);$('draftSelect').value=chosen?.id||'';draftControls();}
  async function refreshDrafts(){if(!server)return;const serial=++draftRefresh;try{const context=await draftAPI('/api/landmark-drafts?workbench='+encodeURIComponent(server.workbench_id));if(serial!==draftRefresh)return;showDrafts(context);$('draftStatus').textContent=context.page_sha256===server.page_sha256?`已保存 ${context.drafts.length} 份草稿。保存采用独立快照；关闭页面前请点击保存。`:'工作区页面已换版，请重新打开后核对草稿。';}catch(error){if(serial===draftRefresh){draftContext=null;draftControls();$('draftStatus').textContent='草稿列表读取失败：'+error.message;}}}
  $('draftSelect').onchange=draftControls;
  $('refreshDrafts').onclick=refreshDrafts;
  $('exportDraft').onclick=()=>{downloadJSON(draftRecord(),'landmark-draft.json');$('draftStatus').textContent='已导出未完成草稿；以后用“载入选点或草稿 JSON”恢复。';};
  $('saveDraft').onclick=async()=>{if(draftBusy||!server||!draftContext)return;const snapshot=draftRecord(),revision=state.revision,label=$('draftLabel').value.trim();if(!label){$('draftStatus').textContent='请先填写草稿名称。';return;}draftBusy=true;draftControls();++draftRefresh;try{const result=await draftAPI('/api/landmark-drafts',{workbench_id:server.workbench_id,page_sha256:server.page_sha256,state_sha256:draftContext.state_sha256,label,draft:snapshot});showDrafts(result);$('draftSelect').value=result.saved_id;$('draftStatus').textContent=revision===state.revision?'草稿已保存。原模型未修改；没有自动计算或提交。':'请求发出时的草稿已保存，之后的新选点尚未保存。';}catch(error){$('draftStatus').textContent='保存失败：'+error.message;}finally{draftBusy=false;draftControls();}};
  $('restoreDraft').onclick=async()=>{if(draftBusy||!server||!draftContext||!$('draftSelect').value)return;const revision=state.revision,id=$('draftSelect').value;draftBusy=true;draftControls();++draftRefresh;try{const result=await draftAPI('/api/landmark-drafts?workbench='+encodeURIComponent(server.workbench_id)+'&draft_id='+encodeURIComponent(id)+'&page_sha256='+server.page_sha256);showDrafts(result);if(revision!==state.revision){$('draftStatus').textContent='读取期间选点已变化，保留当前编辑；请再次点击恢复。';return;}applyDraft(result.draft);$('draftStatus').textContent='已恢复所选草稿，原快照仍保留。';}catch(error){$('draftStatus').textContent='恢复失败：'+error.message;}finally{draftBusy=false;draftControls();}};
  if(server)refreshDrafts();else{$('draftStatus').textContent='当前为独立页面，可导出草稿 JSON；从本地 Web 工作台打开可保存到项目。';draftControls();}
  function sessionRecord(){return {format_version:1,kind:state.kind,unit:'mm',source:{path:models[1].path,sha256:models[1].sourceSha256,group_id_high:models[1].idHighWord??null,fragment_id:models[1].fragmentId??1},target:{path:models[0].path,sha256:models[0].sourceSha256,group_id_high:models[0].idHighWord??null,fragment_id:models[0].fragmentId??0},prepared_path:DATA.preparedPath,candidate_reference:DATA.candidateReference,candidate_label:state.label,transform_source_to_target:clone(state.matrix),point_pairs:state.kind==='manual_landmarks'?clone(state.pairs):[],fit:state.fit?clone(state.fit):null,provenance:'Interactive preview export; no source models or poses modified',created_at:new Date().toISOString()};}
  $('export').onclick=()=>{
    if(state.kind==='manual_stale'){message('对应点已变化，请重新计算后再导出。');return;}
    const session=sessionRecord();
    const blob=new Blob([JSON.stringify(session,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='alignment-session.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('已导出 JSON。用项目的 apply_landmark_alignment.py 核对原文件并另存结果。');
  };
  if(window.parent&&window.parent!==window&&window.location?.protocol==='http:'){
    $('submitStudio').hidden=false;
    $('submitStudio').onclick=()=>{if(state.kind==='manual_stale'){message('对应点已变化，请重新计算。');return;}window.parent.postMessage({type:'reconstruction:alignment-session',session:sessionRecord()},window.location.origin);message('已提交到 Web 工作台核对原文件并另存对齐结果。');};
  }
  $('import').onclick=()=>$('file').click();
  $('file').onchange=async()=>{
    try {
      const file=$('file').files[0];if(!file)return;const revision=state.revision;if(file.size>1000000)throw Error('JSON超过1MB');
      const session=JSON.parse(await file.text());
      if(revision!==state.revision)throw Error('读取期间选点已变化，已保留当前编辑，请重新载入');
      if(session.format==='reconstruction-landmark-draft'){applyDraft(session);return;}
      if(session.format_version!==1||session.unit!=='mm'||session.source.sha256!==models[1].sourceSha256||session.target.sha256!==models[0].sourceSha256)throw new Error('模型哈希、单位或版本不匹配');
      if(!['manual_landmarks','existing_candidate'].includes(session.kind))throw new Error('不支持的选点文件类型');
      if(!Array.isArray(session.point_pairs)||session.point_pairs.length>64)throw new Error('对应点数量不符合要求');
      const maps=models.map(model=>new Map(Array.from(model.originalIds,(id,index)=>[id,index])));
      const used=[new Set(),new Set()];
      const pairs=session.point_pairs.map(pair=>{
        const selected={};
        for(const [key,cloud] of [['target',0],['source',1]]){
          const id=pair[key].id,index=maps[cloud].get(id);
          if(!Number.isInteger(id)||index===undefined||used[cloud].has(id))throw new Error('选点重复或当前预览抽样未包含之前的选点');
          used[cloud].add(id);selected[key]={id,xyz:point(models[cloud],index)};
        }
        return selected;
      });
      let fitted=null,matrix,kind,label;
      if(session.kind==='manual_landmarks'){
        fitted=M.solveRigid(pairs.map(p=>p.source.xyz),pairs.map(p=>p.target.xyz));matrix=fitted.matrix;kind='manual_landmarks';label='载入的对应点刚体对齐';
      } else {
        if(session.candidate_reference?.sha256!==DATA.candidateReference.sha256)throw new Error('已有候选记录已变化，请重新选择');
        const matched=DATA.candidates.find(row=>row.label===session.candidate_label);
        if(!matched)throw new Error('当前页面中找不到该候选');
        matrix=clone(matched.transform);kind='existing_candidate';label=matched.label;
      }
      state.revision++;if(kind==='existing_candidate')$('candidate').value=String(DATA.candidates.findIndex(row=>row.label===label));
      state.pairs=pairs;state.pending=null;state.fit=fitted;state.matrix=matrix;state.kind=kind;state.label=label;
      fitCamera(2);updatePairs();message('已载入并按当前模型重新核对选点。');
    } catch(error){message('载入失败：'+error.message);}
  };
  $('contextNote').textContent=DATA.notes||'';
  $('modelFiles').textContent=models.map(model=>`${model.label} · ${model.path.split(/[\\/]/).pop()} · ${model.originalPoints.toLocaleString()} 点\n${model.path}`).join('\n\n');
  $('modelFiles').style.whiteSpace='pre-line';
  $('sampling').textContent=models.map(model=>`${model.label}：显示 ${model.displayPoints.toLocaleString()} / ${model.originalPoints.toLocaleString()} 点`+(model.previewSelection==='spatial_original_vertices'?'（空间预览）':model.previewSelection==='local_original_vertices'?'（局部完整点）':'')).join('；')+'。选点编号对应原 PLY 顶点。';
  for(let i=0;i<3;i++)fitCamera(i);chooseCandidate();requestAnimationFrame(redraw);
  } catch(error){const status=document.getElementById('status');if(status)status.textContent='页面初始化失败：'+error.message+'。请从 Web 工作台打开已生成的模型页面。';}
})();
