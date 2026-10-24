// Real HTTP-backed FragmentEditor in a simulated DOM; no browser/GPU claim.
'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const base=process.argv[2],scan=process.argv[3],ids=process.argv[4].split(','),requests=[],blobs=[];let submissions=0;
class Element{constructor(){this.value='';this.checked=false;this.disabled=false;this.textContent='';this.children=[];this.listeners={};this.files=[];}append(...v){this.children.push(...v);}replaceChildren(...v){this.children=v;}addEventListener(k,f){(this.listeners[k]??=[]).push(f);}click(){if(this.onclick)return this.onclick();}}
const elements={},$=id=>elements[id]??=new Element();
async function api(path,body){requests.push({path,write:body!==undefined});const response=await fetch(base+path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),data=await response.json();if(!response.ok)throw Error(data.error);return data;}
(async()=>{
 const source=await (await fetch(base+'/web/studio/fragment_editor.js')).text(),context=vm.createContext({module:{exports:{}},Blob,URL:{createObjectURL:b=>{blobs.push(b);return 'blob:check';},revokeObjectURL:()=>{}},setTimeout:()=>0});vm.runInContext(source,context);const Editor=context.module.exports.FragmentEditor;
 const editor=new Editor({api,submit:async()=>{submissions++;return {id:'must-not-run'};},document:{getElementById:$,createElement:()=>new Element()}});await editor.setProject(scan);
 for(let i=0;i<1000&&$('frameDraftSave').disabled;i++)await new Promise(r=>setTimeout(r,10));assert.equal($('frameDraftSave').disabled,false,$('frameDraftStatus').textContent);
 const verified=[];
 for(const id of ids){const expected=await api('/api/frame-drafts?scan='+encodeURIComponent(scan)+'&draft_id='+id+'&index_sha256='+editor.context.index_sha256);$('frameDraftSelect').value=id;editor.review={id:'old-ready-review'};$('fragmentCoordinate').checked=true;await editor.restoreDraft();assert.equal(JSON.stringify(editor.draftRecord()),JSON.stringify(expected.draft));assert.equal($('fragmentCoordinate').checked,false);assert.equal(editor.review,null);assert.equal(editor.preset,null);assert.equal($('fragmentRun').disabled,true);await editor.run();editor.exportDraft();const record=JSON.parse(await blobs.at(-1).text());assert.deepEqual(record.draft,expected.draft);verified.push({id,partial_roi:expected.draft.roi_fields.some(v=>!v),source_frames_exact:expected.draft.source_frames,fusion_fields:expected.draft.fusion_fields});}
 assert.equal(submissions,0);assert.equal(requests.filter(r=>r.write).length,0);
 const result={served_real_controller:true,http_restored_snapshots:verified,coordinate_confirmation_and_review_cleared:true,portable_export_matches:true,no_job_or_review_submission:true,actual_browser_gpu:false};if(process.argv[5])fs.writeFileSync(process.argv[5],JSON.stringify(result,null,2));console.log(JSON.stringify(result));
})().catch(e=>{console.error(e);process.exitCode=1;});
