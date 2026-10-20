'use strict';
/* DOM/WebGL control simulation. This does not verify an actual GPU. */
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
const math=require('../web/landmark-workbench/registration_math.js');
const source=[[0,0,0],[30,0,0],[0,40,0],[0,0,50],[-25,-15,-10],[20,-20,30]];
const transform=[[0,-1,0,100],[1,0,0,200],[0,0,1,400],[0,0,0,1]],target=source.map(p=>math.apply(transform,p));
function pack(points){return Buffer.from(Float32Array.from(points.flat()).buffer).toString('base64');}
function cloud(points,label){return {label,path:'/synthetic/'+label+'.ply',sourceSha256:label,originalPoints:points.length,displayPoints:points.length,xyz:pack(points),rgb:Buffer.alloc(points.length*3,160).toString('base64'),ids:Buffer.from(Uint32Array.from(points.map((_,i)=>i)).buffer).toString('base64')};}
const payload={clouds:[cloud(target,'target'),cloud(source,'source')],candidates:[{label:'direct_best_training',transform}],preparedPath:'/synthetic/prepared',candidateReference:{path:'/synthetic/fit.json',sha256:'fit'}};
const frames=[],blobs=[],posted=[];
class Element {
  constructor(id=''){this.id=id;this.children=[];this.style={};this.value='';this.checked=false;this.disabled=false;this.textContent='';this.clientWidth=400;this.clientHeight=650;this.listeners={};this.files=[];}
  appendChild(x){this.children.push(x);return x;}
  replaceChildren(...items){this.children=items;}
  setAttribute(k,v){this[k]=v;}
  addEventListener(k,f){(this.listeners[k]??=[]).push(f);}
  setPointerCapture(){}
  click(){if(this.onclick)this.onclick();}
  querySelector(){return this.error??=new Element('error');}
  getBoundingClientRect(){return {left:this.id==='source'?400:this.id==='overlay'?800:0,top:0,width:400,height:650};}
  getContext(){
    const element=this,constants={};let counter=1;
    return new Proxy({}, {get(_,key){
      if(key==='getShaderParameter'||key==='getProgramParameter')return ()=>true;
      if(key==='getUniformLocation'||key==='getAttribLocation')return (_,name)=>name;
      if(key==='uniformMatrix4fv')return (_,__,value)=>{assert.ok(Array.from(value).every(Number.isFinite));element.lastMatrix=Array.from(value);};
      if(key==='uniform1f')return (_,value)=>assert.ok(Number.isFinite(value));
      if(key.toUpperCase()===key)return constants[key]??=counter++;
      return ()=>({});
    }});
  }
}
const elements={};const $=id=>elements[id]??=new Element(id);
for(const name of ['target','source','overlay'])$(name).parentElement=new Element(name+'Pane');
$('alignment-data').textContent=JSON.stringify(payload);$('colorMode').value='separate';
const document={getElementById:$,createElement:name=>new Element(name),createElementNS:(_,name)=>new Element(name)};
const context=vm.createContext({document,RegistrationMath:math,Float32Array,Uint32Array,Uint8Array,DataView,Map,Set,Array,Math,Number,JSON,Blob,atob,
  window:{devicePixelRatio:1,parent:{postMessage:(data,origin)=>posted.push({data,origin})},location:{protocol:'http:',origin:'http://127.0.0.1:8877'}},requestAnimationFrame:f=>frames.push(f),setTimeout:()=>0,URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:synthetic';},revokeObjectURL:()=>{}}});
vm.runInContext(fs.readFileSync('web/landmark-workbench/app.js','utf8'),context);
frames.shift()();
assert.equal($('candidate').children.length,1);
assert.equal($('solve').disabled,true);
assert.ok($('target').lastMatrix&&$('source').lastMatrix&&$('overlay').lastMatrix);
async function load(session){$('file').files=[{text:async()=>JSON.stringify(session)}];await $('file').onchange();}
async function exported(){const before=blobs.length;$('export').onclick();assert.equal(blobs.length,before+1);return JSON.parse(await blobs.at(-1).text());}
(async()=>{
  const session={format_version:1,kind:'manual_landmarks',unit:'mm',source:{sha256:'source'},target:{sha256:'target'},
    point_pairs:source.slice(0,4).map((p,i)=>({source:{id:i,xyz:p},target:{id:i,xyz:target[i]}}))};
  await load(session);assert.equal($('pairs').children.length,4);assert.equal($('solve').disabled,false);
  const first=await exported();assert.equal(first.kind,'manual_landmarks');assert.equal(first.point_pairs.length,4);assert.ok(first.fit.rmse<.001);
  assert.ok(Math.max(...first.transform_source_to_target.flat().map((x,i)=>Math.abs(x-transform.flat()[i])))<.001);
  assert.deepEqual(first.candidate_reference,payload.candidateReference);
  $('submitStudio').onclick();assert.equal(posted.length,1);assert.equal(posted[0].data.type,'reconstruction:alignment-session');assert.equal(posted[0].data.session.kind,'manual_landmarks');assert.equal(posted[0].origin,'http://127.0.0.1:8877');
  $('pairs').children[0].children[0].onclick();assert.equal($('export').disabled,true);
  const count=blobs.length;$('export').onclick();assert.equal(blobs.length,count,'stale landmarks cannot export an old fit');
  $('submitStudio').onclick();assert.equal(posted.length,1,'stale landmarks cannot submit an old fit');
  $('restore').onclick();assert.equal($('export').disabled,false);const restored=await exported();assert.equal(restored.kind,'existing_candidate');assert.equal(restored.point_pairs.length,0);
  const pairs=$('pairs').children.length;
  await load({...session,target:{sha256:'wrong'}});assert.match($('status').textContent,/载入失败/);assert.equal($('pairs').children.length,pairs);
  const preserved=await exported();assert.deepEqual(preserved.transform_source_to_target,restored.transform_source_to_target);
  const point=source.map((p,i)=>({i,screen:math.project(p,$('source').lastMatrix,400,650)})).find(row=>row.screen&&math.pickPoint(Float32Array.from(source.flat()),$('source').lastMatrix,400,650,...row.screen.slice(0,2),10)?.index===row.i);
  assert.ok(point);
  $('source').listeners.pointerdown[0]({altKey:true,button:0,clientX:400+point.screen[0],clientY:point.screen[1]});
  assert.match($('status').textContent,/先在左侧/);
  console.log(JSON.stringify({initialization:true,import_fit_export:true,web_parent_submission:true,stale_fit_blocked:true,failed_import_preserves_state:true,pick_order_checked:true,gpu_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
