'use strict';
/* DOM/WebGL control simulation. This does not verify an actual GPU. */
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
const math=require('../web/landmark-workbench/registration_math.js');
const source=[[0,0,0],[30,0,0],[0,40,0],[0,0,50],[-25,-15,-10],[20,-20,30]];
const transform=[[0,-1,0,100],[1,0,0,200],[0,0,1,400],[0,0,0,1]],target=source.map(p=>math.apply(transform,p));
function pack(points){return Buffer.from(Float32Array.from(points.flat()).buffer).toString('base64');}
function cloud(points,label){return {label,path:'/synthetic/'+label+'.ply',sourceSha256:label,originalPoints:points.length,displayPoints:points.length,xyz:pack(points),rgb:Buffer.alloc(points.length*3,160).toString('base64'),ids:Buffer.from(Uint32Array.from(points.map((_,i)=>i)).buffer).toString('base64')};}
let payload={clouds:[cloud(target,'target'),cloud(source,'source')],candidates:[{label:'direct_best_training',transform}],preparedPath:'/synthetic/prepared',candidateReference:{path:'/synthetic/fit.json',sha256:'fit'}};
const served=fs.readFileSync(process.argv[2],'utf8'),saved=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const match=served.match(/<script id="alignment-data" type="application\/json">([\s\S]*?)<\/script>/);assert.ok(match);payload=JSON.parse(match[1]);
const executable=[...served.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);const controller=executable.find(code=>code.includes('function draftRecord()'));assert.ok(controller);
const baseURL=process.argv[4],network=[];
async function httpFetch(path,options){network.push(path);return fetch(baseURL+path,options);}
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
$('saveDraft').disabled=$('restoreDraft').disabled=true;
$('alignment-data').textContent=JSON.stringify(payload);$('colorMode').value='separate';
const document={getElementById:$,createElement:name=>new Element(name),createElementNS:(_,name)=>new Element(name)};
const context=vm.createContext({document,RegistrationMath:math,Float32Array,Uint32Array,Uint8Array,DataView,Map,Set,Array,Math,Number,JSON,Blob,atob,
  fetch:httpFetch,window:{devicePixelRatio:1,parent:{postMessage:(data,origin)=>posted.push({data,origin})},location:{protocol:'http:',origin:'http://127.0.0.1:8877'}},requestAnimationFrame:f=>frames.push(f),setTimeout:()=>0,URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:synthetic';},revokeObjectURL:()=>{}}});
vm.runInContext(controller,context);
frames.shift()();
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
(async()=>{
  for(let i=0;i<1000&&$('saveDraft').disabled;i++)await tick();
  assert.equal($('saveDraft').disabled,false,$('draftStatus').textContent);
  $('draftSelect').value=saved.id;$('draftSelect').onchange();assert.equal($('restoreDraft').disabled,false);
  await $('restoreDraft').onclick();assert.equal($('pairs').children.length,saved.draft.point_pairs.length,$('draftStatus').textContent);
  assert.equal($('export').disabled,saved.draft.requires_recompute);$('exportDraft').onclick();
  const restored=JSON.parse(await blobs.at(-1).text());assert.deepEqual(restored,saved.draft);assert.equal(posted.length,0);
  console.log(JSON.stringify({served_controller_restored_saved_draft:true,original_ids_and_pending_preserved:true,requires_recompute:restored.requires_recompute,point_pairs:restored.point_pairs.length,pending_target:restored.pending_target?.id,network_requests:network.length,no_job_submission:true,gpu_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
