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
viewer.setClouds([source]);viewer.draw();assert.equal(canvas.parentElement.fallback.pixels.length,800*600*4);const original=Array.from(source.colors);viewer.setGain(2);viewer.draw();assert.deepEqual(Array.from(source.colors),original);assert.equal(viewer.clouds[0].colors[0],50);viewer.setGain(1);assert.equal(viewer.clouds[0].colors[0],25,'display gain never compounds');
const screen=math.project([0,0,0],viewer.mvp,800,600);assert.ok(screen);canvas.events.pointerdown({pointerId:1,clientX:screen[0],clientY:screen[1]});canvas.events.pointerup({pointerId:1,clientX:screen[0],clientY:screen[1]});assert.equal(picked[0].id,400);
console.log(JSON.stringify({real_viewer_cpu_fallback:true,real_cpu_pixels:true,source_colors_unchanged:true,exposure_not_compounded:true,original_id_pick:true,actual_browser_verified:false}));
