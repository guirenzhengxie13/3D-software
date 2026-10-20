'use strict';
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
const raster=require('../web/landmark-workbench/point_raster.js'),ply=require('../web/studio/ply_reader.js');
const identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1];
const pixels=raster.rasterize([{points:[0,0,.5,0,0,-.5,2,0,0],colors:[255,0,0,0,255,0,0,0,255]}],identity,20,20,1);
assert.deepEqual(Array.from(pixels.slice((10*20+10)*4,(10*20+10)*4+4)),[0,255,0,255],'nearest point wins');
const hidden=raster.rasterize([{points:[0,0,2],colors:[255,0,0]}],identity,10,10,1);assert.equal(hidden.filter((v,i)=>i%4===0&&v===255).length,0);
const ascii=Buffer.from('ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 1\n.1 .2 1\n.2 .3 1\n');
const array=b=>b.buffer.slice(b.byteOffset,b.byteOffset+b.byteLength),data=ply.parse(array(ascii),'m');assert.deepEqual(Array.from(data.points),[0,0,1000,100,200,1000,200,300,1000]);
for(const little of [true,false]){const header=Buffer.from('ply\nformat binary_'+(little?'little':'big')+'_endian 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n');const points=Buffer.alloc(15);for(let i=0;i<3;i++)points[little?'writeFloatLE':'writeFloatBE'](i+1,i*4);points.set([11,22,33],12);const parsed=ply.parse(array(Buffer.concat([header,points])));assert.deepEqual(Array.from(parsed.points),[1,2,3]);assert.deepEqual(Array.from(parsed.colors),[11,22,33]);}
assert.throws(()=>ply.parse(array(Buffer.from('ply\nformat ascii 1.0\nelement vertex -2\nend_header\n'))));
assert.throws(()=>ply.parse(array(ascii),'unknown'));
// Drive the real generated application controller with a simulated DOM;
// rendering pixels is independently checked above, not called a GPU test.
class Element{
 constructor(id=''){this.id=id;this.children=[];this.value='';this.style={};this.dataset={};this.hidden=false;this.files=[];this.classList={toggle(){}};}
 append(...e){this.children.push(...e);}replaceChildren(...e){this.children=e;}setAttribute(k,v){this[k]=v;}getAttribute(k){return this[k];}
}
const elements={},$=id=>elements[id]??=new Element(id),nav=['workspace','frames','alignment','experiments','workflow'].map(id=>{const e=new Element();e.dataset.tab=id;return e;}),tabs=nav.map(e=>$(e.dataset.tab));
$('pointSize').value='2.5';$('localUnit').value='mm';$('frameSlider').value='0';
const requests=[],catalog={summary:{frames:2,observations:6,projects:1,models:1},projects:[{id:'S',label:'sample',cohort:'test',frames:2,observations:6}],models:[{id:'M',scan_id:'S',role:'baseline',path:'sample.ply',points:3,bytes:100,label:'model'}],workbenches:[{id:'W',label:'landmark-workbench',url:'/workbench.html',models:[{path:'sample.ply',points:3}]}],experiments:[{id:'E',label:'experiment',pages:[{url:'/review.html',label:'review'}],record:'/README.md',status:'candidate'}],reports:[{url:'/report.html',label:'report'}],default_scan:'S'};
class Viewer{constructor(){this.clouds=[];}setClouds(c){this.clouds=c;}fit(){}enableSoftware(){}}
const context=vm.createContext({document:{getElementById:$,createElement:t=>new Element(t),querySelectorAll:q=>q==='.tab'?tabs:nav},PointViewer:Viewer,location:{hash:''},URL,JSON,Set,Map,Number,Math,Array,console,
 setTimeout:()=>0,clearTimeout(){},fetch:async(path,options)=>{requests.push({path,options});return {ok:true,json:async()=>path==='/api/catalog'?catalog:path==='/api/jobs'?[]:path.startsWith('/api/cloud')?{displayPoints:3,originalPoints:3,selection:'real ids'}:{displayPoints:3,originalPoints:3,frame_id:0,pose_available:true,coordinate:'saved',depth_url:'/depth.png'}};}});
vm.runInContext(fs.readFileSync('web/studio/app.js','utf8'),context);
(async()=>{for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));assert.equal($('projectList').children.length,1);assert.equal($('modelList').children.length,1);assert.equal($('viewMessage').hidden,true);assert.equal($('workbenchFrame').src,undefined,'hidden iframe is not initialized at zero width');nav[2].onclick();assert.equal($('workbenchFrame').src,'/workbench.html');assert.equal($('experimentGrid').children.length,1);nav[1].onclick();for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));assert.ok(requests.some(r=>r.path.startsWith('/api/frame')));assert.match($('frameInfo').textContent,/原帧编号/);console.log(JSON.stringify({cpu_depth_raster:true,local_ply_ascii_and_two_endians:true,web_catalog_and_model_controller:true,frame_navigation:true,hidden_iframe_lazy_initialization:true,actual_browser_gpu:false}));})().catch(e=>{console.error(e);process.exitCode=1;});
