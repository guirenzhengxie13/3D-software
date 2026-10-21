'use strict';
/* Exercise the actual Studio viewer class, including WebGL failure, CPU draw,
 * unchanged input colors, exposure updates and original-ID picking. */
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm'),raster=require('../web/landmark-workbench/point_raster.js'),math=require('../web/landmark-workbench/registration_math.js');
const callbacks=[];
class Canvas{
 constructor(){this.style={};this.clientWidth=800;this.clientHeight=600;this.width=800;this.height=600;this.events={};}
 addEventListener(k,f){this.events[k]=f;}setPointerCapture(){}getBoundingClientRect(){return {width:800,height:600,left:0,top:0};}
 getContext(type){return type==='webgl'?null:{createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData:d=>{this.pixels=d.data;}};}
}
const canvas=new Canvas();canvas.parentElement={insertBefore(c){this.fallback=c;}};const badge={},picked=[];
const window={devicePixelRatio:1,addEventListener(){}};const context=vm.createContext({window,document:{createElement:()=>new Canvas()},PointRaster:raster,RegistrationMath:math,Float32Array,Uint8Array,Uint32Array,Uint8ClampedArray,DataView,atob,requestAnimationFrame:f=>callbacks.push(f)});
vm.runInContext(fs.readFileSync('web/studio/point_viewer.js','utf8'),context);
const viewer=new window.PointViewer(canvas,badge,p=>picked.push(p));assert.ok(viewer.software);assert.match(badge.textContent,/Canvas/);
const source={id:'source',points:Float32Array.from([0,0,0,30,0,0,0,40,0,0,0,50]),colors:Uint8Array.from([25,50,75,25,50,75,25,50,75,25,50,75]),originalIds:Uint32Array.from([400,401,402,403])};
const encoded={id:'http-model',points:793214,originalPoints:793214,displayPoints:4,xyz:Buffer.from(source.points.buffer).toString('base64'),rgb:Buffer.from(source.colors.buffer).toString('base64'),ids:Buffer.from(source.originalIds.buffer).toString('base64')};
viewer.setClouds([encoded]);viewer.draw();assert.equal(viewer.clouds[0].points.length,12,'scalar catalog point count cannot shadow base64 coordinates');
viewer.setClouds([source]);viewer.draw();assert.equal(canvas.parentElement.fallback.pixels.length,800*600*4);const original=Array.from(source.colors);viewer.setGain(2);viewer.draw();assert.deepEqual(Array.from(source.colors),original);assert.equal(viewer.clouds[0].colors[0],50);viewer.setGain(1);assert.equal(viewer.clouds[0].colors[0],25,'display gain never compounds');
const screen=math.project([0,0,0],viewer.mvp,800,600);assert.ok(screen);canvas.events.pointerdown({pointerId:1,clientX:screen[0],clientY:screen[1]});canvas.events.pointerup({pointerId:1,clientX:screen[0],clientY:screen[1]});assert.equal(picked[0].id,400);
const originalPoints=Array.from(source.points),originalIds=Array.from(source.originalIds),triples=colors=>new Set(Array.from({length:colors.length/3},(_,i)=>Array.from(colors.slice(i*3,i*3+3)).join(',')));
const modes=['original','depth','height','layer','mono'];
for(const mode of modes){
 viewer.setColorMode(mode);viewer.setGain(1);const baseline=Array.from(viewer.clouds[0].colors);
 for(const gain of [2,1.4,4,1]){viewer.setGain(gain);viewer.draw();}
 assert.deepEqual(Array.from(viewer.clouds[0].colors),baseline,mode+' gain resets without compounding');
 assert.deepEqual(Array.from(viewer.clouds[0].sourceColors),original,'source RGB survives '+mode);
 assert.deepEqual(Array.from(viewer.clouds[0].points),originalPoints,'source geometry survives '+mode);
 assert.deepEqual(Array.from(viewer.clouds[0].originalIds),originalIds,'source IDs survive '+mode);
 if(mode==='height'||mode==='depth')assert.ok(triples(viewer.clouds[0].colors).size>1,mode+' gives varying geometric pseudocolor');
}
assert.deepEqual(Array.from(source.colors),original);assert.deepEqual(Array.from(source.points),originalPoints);assert.deepEqual(Array.from(source.originalIds),originalIds);
const matrices=[];
for(const preset of ['front','side','top','perspective']){viewer.setView(preset);viewer.draw();const matrix=Array.from(viewer.mvp);assert.equal(matrix.length,16);assert.ok(matrix.every(Number.isFinite),preset+' has a finite view matrix');assert.ok(math.project(viewer.camera.target,matrix,800,600),preset+' keeps fitted geometry visible');matrices.push(matrix.join(','));}
assert.equal(new Set(matrices).size,4,'view presets give distinct orientations');
viewer.setColorMode('depth');viewer.setView('front');viewer.draw();const frontColors=Array.from(viewer.clouds[0].colors);viewer.setView('side');viewer.draw();assert.notDeepEqual(Array.from(viewer.clouds[0].colors),frontColors,'depth pseudocolor follows camera rotation');
const gray={...source,colors:new Uint8Array(source.colors.length).fill(165)};viewer.setClouds([gray]);viewer.setColorMode('original');assert.match(viewer.colorDescription(),/统一灰度/);viewer.setClouds([{...gray,has_rgb:false}]);assert.match(viewer.colorDescription(),/未保存 RGB/);
viewer.setClouds([source,{...source,id:'second'}]);viewer.setColorMode('layer');assert.notDeepEqual(Array.from(viewer.clouds[0].colors),Array.from(viewer.clouds[1].colors),'overlaid sources receive distinct layer colors');
// Verify the WebGL upload consumes the same display bytes as the CPU rasterizer.
const buffers=new Map();let bound=null;const gl={ARRAY_BUFFER:1,STATIC_DRAW:2,COMPILE_STATUS:3,LINK_STATUS:4,DEPTH_TEST:5,COLOR_BUFFER_BIT:8,DEPTH_BUFFER_BIT:16,FLOAT:9,UNSIGNED_BYTE:10,POINTS:11,NO_ERROR:0,
 createShader:()=>({}),shaderSource(){},compileShader(){},getShaderParameter:()=>true,createProgram:()=>({}),attachShader(){},linkProgram(){},getProgramParameter:()=>true,useProgram(){},enable(){},clearColor(){},getAttribLocation:()=>0,getUniformLocation:()=>({}),
 createBuffer:()=>({}),bindBuffer:(_,buffer)=>{bound=buffer;},bufferData:(_,data)=>buffers.set(bound,Array.from(data)),deleteBuffer:buffer=>buffers.delete(buffer),viewport(){},clear(){},uniformMatrix4fv(){},uniform1f(){},enableVertexAttribArray(){},vertexAttribPointer(){},drawArrays(){},getError:()=>0};
const glCanvas=new Canvas();glCanvas.getContext=type=>type==='webgl'?gl:null;const glViewer=new window.PointViewer(glCanvas,{});assert.ok(!glViewer.software);viewer.setClouds([source]);glViewer.setClouds([source]);
for(const mode of modes){viewer.setColorMode(mode);glViewer.setColorMode(mode);viewer.setGain(1.6);glViewer.setGain(1.6);viewer.setView('perspective');glViewer.setView('perspective');viewer.draw();glViewer.draw();assert.deepEqual(buffers.get(glViewer.clouds[0].gpu[1]),Array.from(viewer.clouds[0].colors),mode+' shares CPU/WebGL display colors');assert.deepEqual(buffers.get(glViewer.clouds[0].gpu[0]),originalPoints,'WebGL geometry remains unchanged');}
viewer.setColorMode('original');viewer.setGain(1);viewer.setView('perspective');
let network=null;
if(process.argv[2]){
 const payload=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));viewer.setGain(process.argv[4]?1:1.8);viewer.setClouds([payload]);if(process.argv[4])viewer.setColorMode(process.argv[4]);viewer.draw();const pixels=canvas.parentElement.fallback.pixels;let visible=0;
 for(let i=0;i<pixels.length;i+=4)if(pixels[i]!==12||pixels[i+1]!==20||pixels[i+2]!==32)visible++;
 assert.ok(visible>200,'actual HTTP payload produces nonempty point pixels');assert.equal(viewer.clouds[0].originalIds.length,payload.displayPoints);assert.equal(viewer.clouds[0].points.length,payload.displayPoints*3);
 if(process.argv[3])fs.writeFileSync(process.argv[3],pixels);
 network={display_points:payload.displayPoints,visible_pixels:visible,width:800,height:600};
}
console.log(JSON.stringify({real_viewer_cpu_fallback:true,scalar_count_does_not_shadow_coordinates:true,real_cpu_pixels:true,source_colors_unchanged:true,source_geometry_and_ids_unchanged:true,color_modes_and_gain_reset:true,pseudocolor_follows_view:true,four_view_presets:true,cpu_webgl_color_bytes_match:true,exposure_not_compounded:true,original_id_pick:true,actual_http_payload:network,actual_browser_verified:false}));
