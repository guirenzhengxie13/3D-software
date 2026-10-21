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
const elements={},$=id=>elements[id]??=new Element(id),nav=['workspace','experiments','workflow'].map(id=>{const e=new Element();e.dataset.tab=id;return e;}),modes=['workspace','frames','alignment'].map(id=>{const e=new Element();e.dataset.mode=id;return e;}),tabs=['workspace','frames','alignment','experiments','workflow'].map($);
$('pointSize').value='2.5';$('localUnit').value='mm';$('frameSlider').value='0';$('pointBudget').value='40000';
const requests=[],catalog={summary:{frames:2,observations:6,projects:2,models:1},projects:[{id:'EMPTY',label:'empty',cohort:'test',frames:0,observations:0},{id:'S',label:'sample',cohort:'test',frames:2,observations:6}],models:[{id:'M',scan_id:'S',role:'baseline',path:'sample.ply',points:3,bytes:100,label:'model'}],workbenches:[{id:'W',label:'landmark-workbench',url:'/workbench.html',models:[{path:'sample.ply',points:3}]}],experiments:[{id:'E',label:'experiment',pages:[{url:'/review.html',label:'review'}],record:'/README.md',status:'candidate'}],reports:[{url:'/report.html',label:'report'}],default_scan:'UNAVAILABLE'};
const viewers=[];
class Viewer{constructor(){this.clouds=[];this.mode='original';this.gain=1;viewers.push(this);}setClouds(c){this.clouds=c;}setColorMode(mode){this.mode=mode;}setView(preset){this.preset=preset;}setGain(gain){this.gain=gain;}colorDescription(){return '颜色说明：'+this.mode;}fit(){}enableSoftware(){}}
const context=vm.createContext({document:{getElementById:$,createElement:t=>new Element(t),querySelectorAll:q=>q==='.tab'?tabs:q==='[data-mode]'?modes:nav},PointViewer:Viewer,location:{hash:''},URL,JSON,Set,Map,Number,Math,Array,console,
 setTimeout:()=>0,clearTimeout(){},fetch:async(path,options)=>{requests.push({path,options});return {ok:true,json:async()=>path.startsWith('/api/catalog')?catalog:path==='/api/jobs'?[]:path.startsWith('/api/cloud')?{displayPoints:3,originalPoints:3,selection:'real ids'}:{displayPoints:3,originalPoints:3,frame_id:0,pose_available:true,coordinate:'saved',depth_url:'/depth.png'}};}});
vm.runInContext(fs.readFileSync('web/studio/app.js','utf8'),context);
(async()=>{
 for(let i=0;i<12;i++)await new Promise(resolve=>setImmediate(resolve));
 assert.equal($('projectList').children.length,2);assert.equal($('modelList').children.length,1);assert.equal($('viewMessage').hidden,true);
 assert.equal($('contextProject').textContent,'sample','missing default skips a first project without models');
 const cloudRequests=()=>requests.filter(r=>r.path.startsWith('/api/cloud'));
 assert.equal(cloudRequests().length,1);assert.equal(new URL(cloudRequests()[0].path,'http://local').searchParams.get('budget'),'40000');
 for(const budget of [10000,60000,10000]){const before=cloudRequests().length;$('pointBudget').value=String(budget);await $('pointBudget').onchange();assert.equal(cloudRequests().length,before+1,'budget change clears previous loaded models');assert.equal(new URL(cloudRequests().at(-1).path,'http://local').searchParams.get('budget'),String(budget));assert.equal(viewers[0].clouds[0].originalPoints,3,'preview budget does not invent original points');}
 const count=cloudRequests().length;$('pointBudget').value='9999';await $('pointBudget').onchange();assert.equal(cloudRequests().length,count,'unsupported budget is ignored');
 $('colorMode').value='height';$('colorMode').onchange();assert.equal(viewers[0].mode,'height');assert.match($('modelNotice').textContent,/颜色说明：height/);
 $('colorGain').value='1.6';$('colorGain').oninput();assert.equal(viewers[0].gain,1.6);
 $('viewPreset').value='top';$('viewPreset').onchange();assert.equal(viewers[0].preset,'top');assert.equal($('viewPreset').value,'');
 await $('refreshCatalog').onclick();assert.ok(requests.some(r=>r.path==='/api/catalog?refresh=1'),'refresh asks backend to rescan');assert.equal($('contextProject').textContent,'sample');
 assert.equal($('workbenchFrame').src,undefined,'hidden iframe is not initialized at zero width');modes[2].onclick();assert.equal($('workbenchFrame').src,'/workbench.html');assert.equal($('experimentGrid').children.length,1);
 modes[1].onclick();for(let i=0;i<6;i++)await new Promise(resolve=>setImmediate(resolve));assert.ok(requests.some(r=>r.path.startsWith('/api/frame')));assert.match($('frameInfo').textContent,/原帧编号/);
 nav[1].onclick();assert.equal($('workspaceContext').hidden,true);nav[0].onclick();assert.equal(context.location.hash,'frames','project retains the selected working mode');assert.equal($('workspaceContext').hidden,false);assert.equal(nav.length,3);
 console.log(JSON.stringify({cpu_depth_raster:true,local_ply_ascii_and_two_endians:true,web_catalog_and_model_controller:true,missing_default_uses_available_model:true,point_budget_requests_and_cache_reset:true,color_and_view_controls:true,refresh_rescans_catalog:true,frame_navigation:true,three_main_entries:true,shared_project_mode_preserved:true,hidden_iframe_lazy_initialization:true,actual_browser_gpu:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
