/* Shared viewer: WebGL with matched shader precision, plus CPU depth splats. */
(function(root){
 'use strict';
 const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],norm=a=>{const n=Math.hypot(...a)||1;return a.map(x=>x/n);};
 function multiply(a,b){const c=new Float32Array(16);for(let j=0;j<4;j++)for(let i=0;i<4;i++)for(let k=0;k<4;k++)c[j*4+i]+=a[k*4+i]*b[j*4+k];return c;}
 function decode(text,type){if(typeof text!=='string')throw Error('缺少点云编码数据');const bytes=Uint8Array.from(atob(text),x=>x.charCodeAt(0)),v=new DataView(bytes.buffer);if(type==='u8')return bytes;if(bytes.length%4)throw Error('点云编码长度不是4字节的整数倍');return type==='u32'?Uint32Array.from({length:bytes.length/4},(_,i)=>v.getUint32(4*i,true)):Float32Array.from({length:bytes.length/4},(_,i)=>v.getFloat32(4*i,true));}
 const vector=value=>Array.isArray(value)||(ArrayBuffer.isView(value)&&typeof value.length==='number');
 const colorModes=new Set(['original','depth','height','layer','mono']),layerColors=[[92,190,255],[255,178,93],[165,220,133]];
 function colorSummary(colors){let constant=true,gray=true;for(let i=0;i<colors.length;i+=3){if(colors[i]!==colors[0]||colors[i+1]!==colors[1]||colors[i+2]!==colors[2])constant=false;if(colors[i]!==colors[i+1]||colors[i]!==colors[i+2])gray=false;}return {constant,gray};}
 function ramp(t){t=Math.max(0,Math.min(1,t));const stops=[[55,90,220],[45,190,170],[245,220,70]],i=t<.5?0:1,f=t<.5?t*2:(t-.5)*2;return stops[i].map((v,j)=>Math.round(v+(stops[i+1][j]-v)*f));}
 function decodePayload(row){
  // A scalar catalog count must never shadow base64 coordinate arrays.
  const points=vector(row.points)?Float32Array.from(row.points):decode(row.xyz,'f32');
  const colors=vector(row.colors)?Uint8Array.from(row.colors):decode(row.rgb,'u8');
  const originalIds=vector(row.originalIds)?Uint32Array.from(row.originalIds):decode(row.ids,'u32');
  if(points.length%3||points.length!==colors.length||points.length/3!==originalIds.length||!points.every(Number.isFinite))throw Error('点云坐标、颜色或原编号不完整');
  if(row.displayPoints!==undefined&&row.displayPoints!==originalIds.length)throw Error('显示点数与实际数组不一致');
  return {...row,points,colors,originalIds};
 }
 class PointViewer{
  constructor(canvas,badge,onPick){this.canvas=canvas;this.badge=badge;this.onPick=onPick;this.clouds=[];this.sourceRows=[];this.gain=1;this.colorMode='original';this.size=2.5;this.camera={target:[0,0,0],radius:100,distance:350,yaw:1.2,pitch:.15};this.dirty=true;
   try{this.initGL();this.badge.textContent='WebGL';}catch(error){this.enableSoftware();this.badge.textContent='Canvas 兼容绘制';}
   this.events();this.resizeObserver=typeof ResizeObserver!=='undefined'?new ResizeObserver(()=>{this.dirty=true;}):null;this.resizeObserver?.observe(canvas.parentElement);
   const loop=()=>{requestAnimationFrame(loop);if(this.dirty){this.dirty=false;try{this.draw();}catch(error){if(!this.software){try{this.enableSoftware();return;}catch(fallbackError){error=fallbackError;}}this.badge.textContent='绘制失败：'+error.message;this.lastError=error.message;}}};requestAnimationFrame(loop);
  }
  initGL(){const gl=this.canvas.getContext('webgl',{antialias:true});if(!gl)throw Error('WebGL unavailable');this.gl=gl;
   const compile=(type,src)=>{const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
   const p=gl.createProgram();gl.attachShader(p,compile(gl.VERTEX_SHADER,'precision highp float;attribute vec3 aPosition;attribute vec3 aColor;uniform mat4 uMatrix;uniform float uSize;varying highp vec3 vColor;void main(){gl_Position=uMatrix*vec4(aPosition,1.0);gl_PointSize=uSize;vColor=aColor;}'));
   gl.attachShader(p,compile(gl.FRAGMENT_SHADER,'precision highp float;varying highp vec3 vColor;void main(){if(distance(gl_PointCoord,vec2(0.5))>0.5)discard;gl_FragColor=vec4(vColor,1.0);}'));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));
   gl.useProgram(p);gl.enable(gl.DEPTH_TEST);gl.clearColor(.047,.078,.125,1);this.program=p;this.locations={position:gl.getAttribLocation(p,'aPosition'),color:gl.getAttribLocation(p,'aColor'),matrix:gl.getUniformLocation(p,'uMatrix'),size:gl.getUniformLocation(p,'uSize')};
  }
  enableSoftware(){if(this.ctx)return;const c=document.createElement('canvas');c.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';this.canvas.parentElement.insertBefore(c,this.canvas);this.canvas.style.opacity='0';this.canvas.style.position='relative';this.canvas.style.zIndex='1';this.fallback=c;this.ctx=c.getContext('2d');this.software=true;this.badge.textContent='Canvas 兼容绘制';this.dirty=true;}
  setGain(value){this.gain=Math.max(1,Math.min(4,value));this.updateColors();}
  setColorMode(mode){if(!colorModes.has(mode))throw Error('未知显示颜色方式');this.colorMode=mode;this.updateColors();}
  updateColors(){const mode=this.colorMode,direction=this.direction(),scalar=p=>mode==='height'?-p[0]:dot(p,direction);let lo=Infinity,hi=-Infinity;
   if(mode==='height'||mode==='depth')for(const c of this.clouds)for(let i=0;i<c.points.length;i+=3){const value=scalar(c.points.subarray(i,i+3));lo=Math.min(lo,value);hi=Math.max(hi,value);}
   for(let n=0;n<this.clouds.length;n++){const c=this.clouds[n],colors=new Uint8Array(c.sourceColors.length);for(let i=0;i<colors.length;i+=3){let color;
     if(mode==='original')color=c.sourceColors.subarray(i,i+3);else if(mode==='layer')color=layerColors[n%layerColors.length];else if(mode==='mono')color=[185,205,220];else color=ramp(hi>lo?(scalar(c.points.subarray(i,i+3))-lo)/(hi-lo):.5);
     for(let j=0;j<3;j++)colors[i+j]=Math.min(255,Math.round(color[j]*this.gain));}c.colors=colors;
    if(c.gpu&&!this.software){const gl=this.gl;gl.bindBuffer(gl.ARRAY_BUFFER,c.gpu[1]);gl.bufferData(gl.ARRAY_BUFFER,colors,gl.STATIC_DRAW);}}
   this.colorDirectionKey=direction.join(',');this.dirty=true;
  }
  colorDescription(){const descriptions={original:'原始颜色；增亮仅影响显示。',depth:'视深伪彩：蓝远、黄近，随旋转更新，不是真实颜色。',height:'高度伪彩：按工程 −X 轴着色，蓝低、黄高，不是真实颜色。',layer:'图层着色：蓝、橙、绿区分来源，不表示质量优劣。',mono:'单色显示，仅用于观察几何。'},notes=[];
   if(this.clouds.some(c=>c.has_rgb===false))notes.push('有模型未保存 RGB，灰色为显示占位色。');
   if(this.clouds.some(c=>c.has_rgb!==false&&c.colorSummary.constant&&c.colorSummary.gray))notes.push('当前预览只有统一灰度，不能提供纹理细节；可切换视深或高度伪彩观察形状。');
   else if(this.clouds.some(c=>c.has_rgb!==false&&c.colorSummary.gray))notes.push('当前预览是灰度颜色。');
   return notes.concat(descriptions[this.colorMode]).join(' ');
  }
  setClouds(rows,fit=true){this.sourceRows=rows;if(this.gl)for(const old of this.clouds){if(old.gpu){this.gl.deleteBuffer(old.gpu[0]);this.gl.deleteBuffer(old.gpu[1]);}}
   this.clouds=rows.map(row=>{const c=decodePayload(row);c.sourceColors=c.colors;c.colorSummary=colorSummary(c.sourceColors);
    if(this.gl&&!this.software){const gl=this.gl;c.gpu=[c.points,c.colors].map(a=>{const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,a,gl.STATIC_DRAW);return b;});}return c;});if(fit)this.fit();this.updateColors();
  }
  setView(preset){const views={front:[0,0],side:[Math.PI/2,0],top:[0,1.56],perspective:[1.2,.15]};if(!views[preset])throw Error('未知视角');[this.camera.yaw,this.camera.pitch]=views[preset];this.fit();this.dirty=true;}
  fit(){const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const c of this.clouds)for(let i=0;i<c.points.length;i++) {const j=i%3;lo[j]=Math.min(lo[j],c.points[i]);hi[j]=Math.max(hi[j],c.points[i]);}if(!Number.isFinite(lo[0]))return;
   this.camera.target=lo.map((x,i)=>(x+hi[i])/2);this.camera.radius=Math.max(Math.hypot(...hi.map((v,i)=>v-lo[i]))/2,.1);this.camera.distance=this.camera.radius*2.9*Math.max(1,this.canvas.clientHeight/Math.max(1,this.canvas.clientWidth));this.dirty=true;
  }
  direction(){const c=this.camera;return [-Math.sin(c.pitch),Math.cos(c.yaw)*Math.cos(c.pitch),Math.sin(c.yaw)*Math.cos(c.pitch)];}
  matrix(w,h){const c=this.camera,z=this.direction(),x=norm(cross([-1,0,0],z)),y=cross(z,x),eye=c.target.map((v,i)=>v+z[i]*c.distance);
   const v=Float32Array.from([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);const near=Math.max(c.radius*.0005,(c.distance-c.radius*2)*.5),far=c.distance+c.radius*8,f=1/Math.tan(Math.PI/8),nf=1/(near-far);
   return multiply(Float32Array.from([f/(w/h),0,0,0,0,f,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0]),v);
  }
  draw(){const c=this.canvas,ratio=Math.min(root.devicePixelRatio||1,this.software?1:2),w=Math.max(1,Math.round(c.clientWidth*ratio)),h=Math.max(1,Math.round(c.clientHeight*ratio));if(c.width!==w)c.width=w;if(c.height!==h)c.height=h;this.mvp=this.matrix(w,h);
   if(this.colorMode==='depth'&&this.colorDirectionKey!==this.direction().join(','))this.updateColors();
   if(this.software){this.fallback.width=w;this.fallback.height=h;const data=this.ctx.createImageData(w,h);data.data.set(PointRaster.rasterize(this.clouds,this.mvp,w,h,this.size));this.ctx.putImageData(data,0,0);return;}
   const gl=this.gl,l=this.locations;gl.viewport(0,0,w,h);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.uniformMatrix4fv(l.matrix,false,this.mvp);gl.uniform1f(l.size,this.size*ratio);
   for(const cloud of this.clouds){gl.bindBuffer(gl.ARRAY_BUFFER,cloud.gpu[0]);gl.enableVertexAttribArray(l.position);gl.vertexAttribPointer(l.position,3,gl.FLOAT,false,0,0);gl.bindBuffer(gl.ARRAY_BUFFER,cloud.gpu[1]);gl.enableVertexAttribArray(l.color);gl.vertexAttribPointer(l.color,3,gl.UNSIGNED_BYTE,true,0,0);gl.drawArrays(gl.POINTS,0,cloud.points.length/3);}
   const error=gl.getError();if(error!==gl.NO_ERROR)throw Error('WebGL绘制错误 0x'+error.toString(16));
  }
  events(){let drag=null;const c=this.canvas;c.addEventListener('pointerdown',e=>{drag={id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey};c.setPointerCapture(e.pointerId);});
   c.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;const a=this.camera;if(drag.pan||e.shiftKey){const z=this.direction(),x=norm(cross([-1,0,0],z)),y=cross(z,x),s=a.distance*.85/Math.max(c.clientHeight,1);a.target=a.target.map((v,i)=>v-x[i]*dx*s+y[i]*dy*s);}else{a.yaw-=dx*.008;a.pitch=Math.max(-1.56,Math.min(1.56,a.pitch+dy*.008));}this.dirty=true;});
   c.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<4&&this.onPick&&this.mvp){const r=c.getBoundingClientRect();let best=null;for(const cloud of this.clouds){const p=RegistrationMath.pickPoint(cloud.points,this.mvp,r.width,r.height,e.clientX-r.left,e.clientY-r.top,10);if(p&&(!best||p.distanceSquared<best.hit.distanceSquared))best={cloud,hit:p};}if(best){const i=best.hit.index;this.onPick({model:best.cloud,id:Number(best.cloud.originalIds[i]),xyz:Array.from(best.cloud.points.slice(i*3,i*3+3))});}}drag=null;});
   for(const event of ['pointercancel','lostpointercapture'])c.addEventListener(event,()=>{drag=null;});c.addEventListener('wheel',e=>{e.preventDefault();this.camera.distance=Math.max(this.camera.radius*.08,Math.min(this.camera.radius*100,this.camera.distance*Math.exp(Math.max(-100,Math.min(100,e.deltaY))*.003)));this.dirty=true;},{passive:false});
   c.addEventListener('webglcontextlost',e=>{e.preventDefault();this.enableSoftware();});root.addEventListener?.('resize',()=>{this.dirty=true;});
  }
 }
 root.PointViewer=PointViewer;root.decodeCloudArray=decode;root.decodeCloudPayload=decodePayload;
})(typeof window!=='undefined'?window:globalThis);
