'use strict';
/* DOM/WebGL control simulation. This does not verify an actual GPU. */
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
const math=require('../web/landmark-workbench/registration_math.js');
const source=[[0,0,0],[30,0,0],[0,40,0],[0,0,50],[-25,-15,-10],[20,-20,30]];
const transform=[[0,-1,0,100],[1,0,0,200],[0,0,1,400],[0,0,0,1]],target=source.map(p=>math.apply(transform,p));
function pack(points){return Buffer.from(Float32Array.from(points.flat()).buffer).toString('base64');}
function cloud(points,label){return {label,path:'/synthetic/'+label+'.ply',sourceSha256:label,originalPoints:points.length,displayPoints:points.length,xyz:pack(points),rgb:Buffer.alloc(points.length*3,160).toString('base64'),ids:Buffer.from(Uint32Array.from(points.map((_,i)=>i)).buffer).toString('base64')};}
const payload={clouds:[cloud(target,'target'),cloud(source,'source')],candidates:[{label:'direct_best_training',transform}],preparedPath:'/synthetic/prepared',candidateReference:{path:'/synthetic/fit.json',sha256:'fit'}};
payload.serverContext={workbench_id:'test-workbench',page_sha256:'a'.repeat(64)};
const frames=[],blobs=[],posted=[],requests=[];
let serverState={page_sha256:payload.serverContext.page_sha256,state_sha256:'empty',drafts:[]},savedDraft=null,deferNext=false,release=null,failRead=false;
async function fakeFetch(path,options={}){
  requests.push({path,options});
  if(deferNext){deferNext=false;await new Promise(resolve=>{release=resolve;});}
  if(failRead&&!options.method)return {ok:false,json:async()=>({error:'simulated missing inputs'})};
  let result;
  if(options.method==='POST'){
    const body=JSON.parse(options.body);assert.equal(body.state_sha256,serverState.state_sha256);savedDraft=body.draft;
    serverState={...serverState,state_sha256:'saved-1',drafts:[{id:'draft-1',label:body.label,pairs:savedDraft.point_pairs.length,pending:!!savedDraft.pending_target,available:true,created_at:'2026-10-24T00:00:00+00:00'}]};result={...serverState,saved_id:'draft-1'};
  } else result=path.includes('draft_id=')?{...serverState,draft:savedDraft}:serverState;
  return {ok:true,json:async()=>JSON.parse(JSON.stringify(result))};
}
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
  fetch:fakeFetch,window:{devicePixelRatio:1,parent:{postMessage:(data,origin)=>posted.push({data,origin})},location:{protocol:'http:',origin:'http://127.0.0.1:8877'}},requestAnimationFrame:f=>frames.push(f),setTimeout:()=>0,URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:synthetic';},revokeObjectURL:()=>{}}});
vm.runInContext(fs.readFileSync('web/landmark-workbench/app.js','utf8'),context);
frames.shift()();
const flush=()=>new Promise(resolve=>setImmediate(resolve));
async function load(record){$('file').files=[{size:100,text:async()=>JSON.stringify(record)}];await $('file').onchange();}
async function exportedDraft(){const before=blobs.length;$('exportDraft').onclick();assert.equal(blobs.length,before+1);return JSON.parse(await blobs.at(-1).text());}
(async()=>{
  await flush();assert.equal($('saveDraft').disabled,false);assert.equal($('restoreDraft').disabled,true);
  const session={format_version:1,kind:'manual_landmarks',unit:'mm',source:{sha256:'source'},target:{sha256:'target'},point_pairs:source.slice(0,4).map((p,i)=>({source:{id:i,xyz:p},target:{id:i,xyz:target[i]}}))};
  await load(session);const fitted=await exportedDraft();assert.equal(fitted.requires_recompute,true);assert.equal(fitted.point_pairs.length,4);assert.equal(fitted.candidate_sha256,'fit');assert.ok(!('transform_source_to_target' in fitted));assert.match($('metrics').textContent,/RMS 半径/);
  $('pairs').children[0].children[0].onclick();assert.equal($('export').disabled,true);const dirty=await exportedDraft();assert.equal(dirty.point_pairs.length,3);assert.equal(dirty.requires_recompute,true);
  const partial={...fitted,point_pairs:fitted.point_pairs.slice(0,1),pending_target:fitted.point_pairs[2].target};await load(partial);assert.equal($('pairs').children.length,1);assert.equal($('solve').disabled,true);assert.equal($('export').disabled,true);assert.deepEqual(await exportedDraft(),partial);
  $('draftLabel').value='Simulated incomplete selection';deferNext=true;const saving=$('saveDraft').onclick();await flush();assert.ok(release);$('clearPairs').onclick();release();await saving;
  assert.equal($('pairs').children.length,0);assert.equal(savedDraft.point_pairs.length,1);assert.match($('draftStatus').textContent,/尚未保存/);assert.equal($('restoreDraft').disabled,false);assert.equal(posted.length,0,'saving must never submit alignment');
  deferNext=true;const restoring=$('restoreDraft').onclick();await flush();$('restore').onclick();release();await restoring;assert.equal($('pairs').children.length,0);assert.match($('draftStatus').textContent,/保留当前编辑/);
  await $('restoreDraft').onclick();assert.equal($('pairs').children.length,1);assert.deepEqual(await exportedDraft(),partial);assert.equal($('export').disabled,true);assert.equal(posted.length,0);
  await load({...partial,candidate_sha256:'changed'});assert.match($('status').textContent,/载入失败/);assert.deepEqual(await exportedDraft(),partial);
  await load({...partial,point_pairs:[{...partial.point_pairs[0],source:{id:0,xyz:[9,9,9]}}]});assert.match($('status').textContent,/载入失败/);assert.deepEqual(await exportedDraft(),partial);
  let finish;const oldRead=new Promise(resolve=>{finish=resolve;});$('file').files=[{size:100,text:()=>oldRead}];const importing=$('file').onchange();$('clearPairs').onclick();finish(JSON.stringify(partial));await importing;assert.equal($('pairs').children.length,0);assert.match($('status').textContent,/读取期间/);
  await load(fitted);assert.equal($('export').disabled,true);assert.equal(posted.length,0);$('solve').onclick();assert.equal($('export').disabled,false);$('submitStudio').onclick();assert.equal(posted.length,1,'only explicit submission starts alignment');
  const beforeFailure=await exportedDraft();failRead=true;await $('refreshDrafts').onclick();assert.equal($('saveDraft').disabled,true);assert.match($('draftStatus').textContent,/读取失败/);assert.deepEqual(await exportedDraft(),beforeFailure);
  console.log(JSON.stringify({portable_partial_and_pending:true,dirty_manual_requires_recompute:true,server_snapshot_preserves_later_edits:true,stale_restore_and_import_blocked:true,candidate_and_original_ids_checked:true,no_implicit_submission:true,coverage_display:true,requests:requests.length,gpu_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
