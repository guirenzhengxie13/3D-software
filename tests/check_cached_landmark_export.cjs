'use strict';
/* Synthetic control of generated HTML data and UI logic; no actual GPU. */
const assert=require('assert/strict'),fs=require('fs'),vm=require('vm');
const math=require('../web/landmark-workbench/registration_math.js');
const [pagePath,sessionPath,outPath]=process.argv.slice(2);
const html=fs.readFileSync(pagePath,'utf8'),payload=JSON.parse(html.match(/<script id="alignment-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
const callbacks=[],blobs=[];
class Element {
  constructor(id=''){this.id=id;this.children=[];this.style={};this.value='';this.checked=false;this.disabled=false;this.textContent='';this.files=[];this.clientWidth=400;this.clientHeight=650;}
  appendChild(x){this.children.push(x);return x;} replaceChildren(...x){this.children=x;} setAttribute(k,v){this[k]=v;} addEventListener(){} setPointerCapture(){} click(){if(this.onclick)this.onclick();}
  querySelector(){return this.error??=new Element();} getBoundingClientRect(){return {left:0,top:0,width:400,height:650};}
  getContext(){let value=1;const constants={};return new Proxy({},{get:(_,key)=>{
    if(key==='getShaderParameter'||key==='getProgramParameter')return ()=>true;
    if(key==='getUniformLocation'||key==='getAttribLocation')return (_,name)=>name;
    if(key==='uniformMatrix4fv')return (_,__,array)=>assert.ok(Array.from(array).every(Number.isFinite));
    if(key.toUpperCase()===key)return constants[key]??=value++;
    return ()=>({});
  }});}
}
const elements={},$=id=>elements[id]??=new Element(id);
for(const name of ['target','source','overlay'])$(name).parentElement=new Element();
$('alignment-data').textContent=JSON.stringify(payload);$('colorMode').value='separate';
const context=vm.createContext({document:{getElementById:$,createElement:name=>new Element(name),createElementNS:(_,name)=>new Element(name)},
  RegistrationMath:math,Float32Array,Uint32Array,Uint8Array,DataView,Map,Set,Array,Math,Number,JSON,Blob,atob,
  window:{devicePixelRatio:1},requestAnimationFrame:f=>callbacks.push(f),setTimeout:()=>0,
  URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:synthetic';},revokeObjectURL:()=>{}}});
vm.runInContext(scripts.at(-1)[1],context);callbacks.shift()();
(async()=>{
  const session=JSON.parse(fs.readFileSync(sessionPath,'utf8'));
  for(const [name,cloud] of [['target',0],['source',1]]){
    // Buffer byte offsets are respected when checking the original IDs.
    const bytes=Buffer.from(payload.clouds[cloud].ids,'base64'),view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),actual=new Set();
    for(let i=0;i<bytes.byteLength/4;i++)actual.add(view.getUint32(i*4,true));
    for(const pair of session.point_pairs)assert.ok(actual.has(pair[name].id));
  }
  $('file').files=[{text:async()=>JSON.stringify(session)}];await $('file').onchange();
  assert.match($('status').textContent,/已载入/);$('export').onclick();assert.equal(blobs.length,1);
  const exported=JSON.parse(await blobs[0].text());assert.equal(exported.kind,'manual_landmarks');
  assert.deepEqual(exported.point_pairs.map(p=>[p.source.id,p.target.id]),session.point_pairs.map(p=>[p.source.id,p.target.id]));
  assert.ok(exported.point_pairs.some(p=>p.source.id>payload.clouds[1].displayPoints));
  exported.fixture='Automated synthetic cache/UI/original-ID control; no human annotation';fs.writeFileSync(outPath,JSON.stringify(exported,null,2));
  process.stdout.write(JSON.stringify({cached_original_ids_exported:true,synthetic_only:true,actual_gpu_verified:false})+'\n');
})().catch(error=>{process.stderr.write(String(error.stack||error));process.exitCode=1;});
