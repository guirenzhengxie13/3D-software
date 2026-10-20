'use strict';
/* Execute generated workbench controllers with WebGL absent, and inspect the
 * real CPU pixel output. This is an offline regression, not a Chrome test. */
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),vm=require('vm');
const root=path.resolve(__dirname,'..'),out=path.join(root,'reports/web-studio/compatibility');fs.mkdirSync(out,{recursive:true});
const pages=[];function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){const p=path.join(dir,e.name);if(e.isDirectory())walk(p);else if(e.name.endsWith('.html')&&e.name.includes('workbench'))pages.push(p);}}
walk(path.join(root,'reports/range2-study-20261018'));walk(path.join(root,'reports/pointcloud-scale-20261019'));
if(fs.existsSync(path.join(root,'reports/web-studio/runs')))walk(path.join(root,'reports/web-studio/runs'));
const results=[];
for(const page of pages){
 const html=fs.readFileSync(page,'utf8'),match=html.match(/<script id="alignment-data" type="application\/json">([\s\S]*?)<\/script>/);if(!match)continue;
 const payload=JSON.parse(match[1]),callbacks=[];
 class Element{
  constructor(id=''){this.id=id;this.children=[];this.style={};this.value='';this.checked=false;this.disabled=false;this.textContent='';this.clientWidth=400;this.clientHeight=650;this.width=400;this.height=650;this.listeners={};}
  appendChild(e){e.parentElement=this;this.children.push(e);return e;}replaceChildren(...e){this.children=e;}setAttribute(k,v){this[k]=v;}addEventListener(k,f){(this.listeners[k]??=[]).push(f);}setPointerCapture(){}getBoundingClientRect(){return {width:400,height:650,left:0,top:0};}
  querySelector(){return this.error??=new Element('error');}getContext(type){if(type==='webgl')return null;if(type==='2d')return {createImageData:(w,h)=>({data:new Uint8ClampedArray(w*h*4)}),putImageData:(data)=>{this.pixels=data.data;}};return null;}
 }
 const elements={},$=id=>elements[id]??=new Element(id);for(const name of ['target','source','overlay'])$(name).parentElement=new Element(name+'Pane');$('alignment-data').textContent=JSON.stringify(payload);$('colorMode').value='separate';
 const context=vm.createContext({document:{getElementById:$,createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)},Float32Array,Uint32Array,Uint8Array,Uint8ClampedArray,DataView,Map,Set,Array,Math,Number,JSON,Blob,atob,
  window:{devicePixelRatio:1},requestAnimationFrame:f=>callbacks.push(f),setTimeout:()=>0,URL:{},console});
 for(const script of html.matchAll(/<script>([\s\S]*?)<\/script>/g))vm.runInContext(script[1],context);
 assert.match($('rendererStatus').textContent,/兼容绘制/);assert.ok(callbacks.length,'initialization reaches drawing');callbacks.shift()();
 const views=[];for(const name of ['target','source','overlay']){const canvas=$(name).parentElement.children.find(e=>e.pixels);assert.ok(canvas,`${name} produced CPU pixels`);let visible=0;for(let i=0;i<canvas.pixels.length;i+=4)if(canvas.pixels[i]!==12||canvas.pixels[i+1]!==20||canvas.pixels[i+2]!==32)visible++;assert.ok(visible>200,`${name} nonempty point cloud`);views.push({name,visible_pixels:visible,width:canvas.width,height:canvas.height});if(page.includes('cup-direct-split')&&page.endsWith('landmark-workbench.html'))fs.writeFileSync(path.join(out,name+'.rgba'),canvas.pixels);}
 assert.match($('modelFiles').textContent,/\.ply/);results.push({page,views,files_visible_in_controller:true,webgl_absent_fallback_passed:true});
}
fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify({pages:results,actual_browser_verified:false,actual_gpu_verified:false,method:'Generated HTML scripts and actual CPU raster bytes under a minimal DOM control'},null,2));
console.log(JSON.stringify({generated_pages:results.length,nonempty_cpu_views:results.reduce((s,r)=>s+r.views.length,0),actual_browser_verified:false}));
