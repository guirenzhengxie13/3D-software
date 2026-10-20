/* Shared viewer: WebGL with matched shader precision, plus CPU depth splats. */
(function(root){
 'use strict';
 const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0),cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]],norm=a=>{const n=Math.hypot(...a)||1;return a.map(x=>x/n);};
 function multiply(a,b){const c=new Float32Array(16);for(let j=0;j<4;j++)for(let i=0;i<4;i++)for(let k=0;k<4;k++)c[j*4+i]+=a[k*4+i]*b[j*4+k];return c;}
 function decode(text,type){const bytes=Uint8Array.from(atob(text),x=>x.charCodeAt(0)),v=new DataView(bytes.buffer);if(type==='u8')return bytes;return type==='u32'?Uint32Array.from({length:bytes.length/4},(_,i)=>v.getUint32(4*i,true)):Float32Array.from({length:bytes.length/4},(_,i)=>v.getFloat32(4*i,true));}
 class PointViewer{
  constructor(canvas,badge,onPick){this.canvas=canvas;this.badge=badge;this.onPick=onPick;this.clouds=[];this.sourceRows=[];this.gain=1.8;this.size=2.5;this.camera={target:[0,0,0],radius:100,distance:350,yaw:1.2,pitch:.15};this.dirty=true;
   try{this.initGL();this.badge.textContent='WebGL';}catch(error){this.enableSoftware();this.badge.textContent='Canvas 兼容绘制';}
   this.events();this.resizeObserver=typeof ResizeObserver!=='undefined'?new ResizeObserver(()=>{this.dirty=true;}):null;this.resizeObserver?.observe(canvas.parentElement);
   const loop=()=>{requestAnimationFrame(loop);if(this.dirty){this.dirty=false;this.draw();}};requestAnimationFrame(loop);
  }
  initGL(){const gl=this.canvas.getContext('webgl',{antialias:true});if(!gl)throw Error('WebGL unavailable');this.gl=gl;
   const compile=(type,src)=>{const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
   const p=gl.createProgram();gl.attachShader(p,compile(gl.VERTEX_SHADER,'precision highp float;attribute vec3 aPosition;attribute vec3 aColor;uniform mat4 uMatrix;uniform float uSize;varying highp vec3 vColor;void main(){gl_Position=uMatrix*vec4(aPosition,1.0);gl_PointSize=uSize;vColor=aColor;}'));
   gl.attachShader(p,compile(gl.FRAGMENT_SHADER,'precision highp float;varying highp vec3 vColor;void main(){if(distance(gl_PointCoord,vec2(0.5))>0.5)discard;gl_FragColor=vec4(vColor,1.0);}'));gl.linkProgram(p);if(!gl.getProgramParameter(p,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(p));
   gl.useProgram(p);gl.enable(gl.DEPTH_TEST);gl.clearColor(.047,.078,.125,1);this.program=p;this.locations={position:gl.getAttribLocation(p,'aPosition'),color:gl.getAttribLocation(p,'aColor'),matrix:gl.getUniformLocation(p,'uMatrix'),size:gl.getUniformLocation(p,'uSize')};
  }
  enableSoftware(){if(this.ctx)return;const c=document.createElement('canvas');c.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none';this.canvas.parentElement.insertBefore(c,this.canvas);this.canvas.style.opacity='0';this.canvas.style.position='relative';this.canvas.style.zIndex='1';this.fallback=c;this.ctx=c.getContext('2d');this.software=true;this.badge.textContent='Canvas 兼容绘制';this.dirty=true;}
  setGain(value){this.gain=Math.max(1,Math.min(4,value));this.setClouds(this.sourceRows,false);}
  setClouds(rows,fit=true){this.sourceRows=rows;if(this.gl)for(const old of this.clouds){if(old.gpu){this.gl.deleteBuffer(old.gpu[0]);this.gl.deleteBuffer(old.gpu[1]);}}
   this.clouds=rows.map((row,i)=>{const c={...row,points:row.points||decode(row.xyz,'f32'),colors:row.colors||decode(row.rgb,'u8'),originalIds:row.originalIds||decode(row.ids,'u32')};
    if(c.points.length!==c.colors.length||c.points.length/3!==c.originalIds.length||!c.points.every(Number.isFinite))throw Error('点云数组格式不完整');
    if(rows.length>1){const tint=i===0?[92,190,255]:[255,178,93];c.colors=new Uint8Array(c.colors.length);for(let j=0;j<c.colors.length;j+=3)c.colors.set(tint,j);}else c.colors=Uint8Array.from(c.colors,value=>Math.min(255,Math.round(value*this.gain)));
    if(this.gl&&!this.software){const gl=this.gl;c.gpu=[c.points,c.colors].map(a=>{const b=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,b);gl.bufferData(gl.ARRAY_BUFFER,a,gl.STATIC_DRAW);return b;});}return c;});if(fit)this.fit();this.dirty=true;
  }
  fit(){const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const c of this.clouds)for(let i=0;i<c.points.length;i++) {const j=i%3;lo[j]=Math.min(lo[j],c.points[i]);hi[j]=Math.max(hi[j],c.points[i]);}if(!Number.isFinite(lo[0]))return;
   this.camera.target=lo.map((x,i)=>(x+hi[i])/2);this.camera.radius=Math.max(Math.hypot(...hi.map((v,i)=>v-lo[i]))/2,.1);this.camera.distance=this.camera.radius*2.9*Math.max(1,this.canvas.clientHeight/Math.max(1,this.canvas.clientWidth));this.dirty=true;
  }
  direction(){const c=this.camera;return [-Math.sin(c.pitch),Math.cos(c.yaw)*Math.cos(c.pitch),Math.sin(c.yaw)*Math.cos(c.pitch)];}
  matrix(w,h){const c=this.camera,z=this.direction(),x=norm(cross([-1,0,0],z)),y=cross(z,x),eye=c.target.map((v,i)=>v+z[i]*c.distance);
   const v=Float32Array.from([x[0],y[0],z[0],0,x[1],y[1],z[1],0,x[2],y[2],z[2],0,-dot(x,eye),-dot(y,eye),-dot(z,eye),1]);const near=Math.max(c.radius*.0005,(c.distance-c.radius*2)*.5),far=c.distance+c.radius*8,f=1/Math.tan(Math.PI/8),nf=1/(near-far);
   return multiply(Float32Array.from([f/(w/h),0,0,0,0,f,0,0,0,0,(far+near)*nf,-1,0,0,2*far*near*nf,0]),v);
  }
  draw(){const c=this.canvas,ratio=Math.min(root.devicePixelRatio||1,this.software?1:2),w=Math.max(1,Math.round(c.clientWidth*ratio)),h=Math.max(1,Math.round(c.clientHeight*ratio));if(c.width!==w)c.width=w;if(c.height!==h)c.height=h;this.mvp=this.matrix(w,h);
   if(this.software){this.fallback.width=w;this.fallback.height=h;const data=this.ctx.createImageData(w,h);data.data.set(PointRaster.rasterize(this.clouds,this.mvp,w,h,this.size));this.ctx.putImageData(data,0,0);return;}
   const gl=this.gl,l=this.locations;gl.viewport(0,0,w,h);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.uniformMatrix4fv(l.matrix,false,this.mvp);gl.uniform1f(l.size,this.size*ratio);
   for(const cloud of this.clouds){gl.bindBuffer(gl.ARRAY_BUFFER,cloud.gpu[0]);gl.enableVertexAttribArray(l.position);gl.vertexAttribPointer(l.position,3,gl.FLOAT,false,0,0);gl.bindBuffer(gl.ARRAY_BUFFER,cloud.gpu[1]);gl.enableVertexAttribArray(l.color);gl.vertexAttribPointer(l.color,3,gl.UNSIGNED_BYTE,true,0,0);gl.drawArrays(gl.POINTS,0,cloud.points.length/3);}
  }
  events(){let drag=null;const c=this.canvas;c.addEventListener('pointerdown',e=>{drag={id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey};c.setPointerCapture(e.pointerId);});
   c.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;const a=this.camera;if(drag.pan||e.shiftKey){const z=this.direction(),x=norm(cross([-1,0,0],z)),y=cross(z,x),s=a.distance*.85/Math.max(c.clientHeight,1);a.target=a.target.map((v,i)=>v-x[i]*dx*s+y[i]*dy*s);}else{a.yaw-=dx*.008;a.pitch=Math.max(-1.56,Math.min(1.56,a.pitch+dy*.008));}this.dirty=true;});
   c.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<4&&this.onPick&&this.mvp){const r=c.getBoundingClientRect();let best=null;for(const cloud of this.clouds){const p=RegistrationMath.pickPoint(cloud.points,this.mvp,r.width,r.height,e.clientX-r.left,e.clientY-r.top,10);if(p&&(!best||p.distanceSquared<best.hit.distanceSquared))best={cloud,hit:p};}if(best){const i=best.hit.index;this.onPick({model:best.cloud,id:Number(best.cloud.originalIds[i]),xyz:Array.from(best.cloud.points.slice(i*3,i*3+3))});}}drag=null;});
   for(const event of ['pointercancel','lostpointercapture'])c.addEventListener(event,()=>{drag=null;});c.addEventListener('wheel',e=>{e.preventDefault();this.camera.distance=Math.max(this.camera.radius*.08,Math.min(this.camera.radius*100,this.camera.distance*Math.exp(Math.max(-100,Math.min(100,e.deltaY))*.003)));this.dirty=true;},{passive:false});
   c.addEventListener('webglcontextlost',e=>{e.preventDefault();this.enableSoftware();});root.addEventListener?.('resize',()=>{this.dirty=true;});
  }
 }
 root.PointViewer=PointViewer;root.decodeCloudArray=decode;
})(typeof window!=='undefined'?window:globalThis);
