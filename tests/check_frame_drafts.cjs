/* Real frame editor controller; simulated DOM/requests, no browser/GPU claim. */
'use strict';
const assert=require('assert/strict'),{FragmentEditor}=require('../web/studio/fragment_editor.js');
class Element{
 click(){if(this.onclick)return this.onclick();}
 constructor(){this.files=[];this.value='';this.checked=false;this.disabled=false;this.textContent='';this.children=[];this.listeners={};}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}input(){for(const fn of this.listeners.input||[])fn();}
}
function setup(apiOverride){
 const elements={},$=id=>elements[id]??=new Element(),requests=[],submitted=[],notifications=[];
 const context={scan_id:'A',index_sha256:'a'.repeat(64),frame_count:3,frames:[{ordinal:1,frame_id:'0',depth_present:true,optimized_pose_present:true},{ordinal:2,frame_id:'8',depth_present:true,optimized_pose_present:false},{ordinal:3,frame_id:'1152921504606846976',depth_present:true,optimized_pose_present:true}],
  alignments:[{id:'AL',label:'verified',relative_path:'reports/verified/summary.json',sha256:'b'.repeat(64),candidates:['manual_landmarks'],source:{label:'moving'},target:{label:'fixed'}}],
  presets:[{id:'P',label:'recorded frames',sha256:'c'.repeat(64),alignment_ids:['AL'],source_text:'1152921504606846976',target_text:'0',source_basis:'recorded source basis',target_basis:'recorded target basis',roi:[[0,0,1],[10,10,20]]}]};
 const review={id:'R',plan_sha256:'d'.repeat(64),review_sha256:'e'.repeat(64),summary:{target_frames:1,source_frames:1,selected_frames:2,unselected_frames:1,valid_saved_depth_observations_before_roi:8,pinned_files:12},source_frame_ids:['1152921504606846976'],target_frame_ids:['0'],roi:[[0,0,1],[10,10,20]]};
 const api=async(path,body)=>{requests.push({path,body});if(apiOverride)return apiOverride(path,body,context,review);return path.startsWith('/api/fragments/context')?context:review;};
 const editor=new FragmentEditor({api,submit:async request=>{submitted.push(request);return {id:'JOB'};},notify:(...args)=>notifications.push(args),document:{getElementById:$,createElement:()=>new Element()}});
 return {editor,$,context,review,requests,submitted,notifications};
}
function ready(f){f.$('fragmentPreset').value='P';f.editor.applyPreset();f.$('fragmentDecision').value='Scripted controller check, not human geometry validation';f.$('fragmentCoordinate').checked=true;}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
let state={scan_id:'A',index_sha256:'a'.repeat(64),state_sha256:'empty',drafts:[]},snapshots=new Map(),serial=0,deferSave=false,deferRestore=false,release,fail=false;
function metadata(){return JSON.parse(JSON.stringify(state));}
const f=setup(async(path,body,context,review)=>{
 if(path.startsWith('/api/fragments/context'))return context;
 if(fail)throw Error('simulated input unavailable');
 if(path==='/api/frame-drafts'&&body){if(body.state_sha256!==state.state_sha256)throw Error('stale writer');const draft=JSON.parse(JSON.stringify(body.draft));if(deferSave){deferSave=false;await new Promise(resolve=>{release=resolve;});}const id='saved-'+(++serial);snapshots.set(id,draft);state={...state,state_sha256:id,drafts:[{id,label:body.label,created_at:'2026-10-25T00:00:00Z',available:true},...state.drafts]};return {...metadata(),saved_id:id};}
 if(path.includes('/api/frame-drafts?')&&path.includes('draft_id=')){const id=new URL('http://test'+path).searchParams.get('draft_id');if(deferRestore){deferRestore=false;await new Promise(resolve=>{release=resolve;});}return {...metadata(),draft:snapshots.get(id),alignment_id:'AL'};}
 if(path.startsWith('/api/frame-drafts?'))return metadata();
 if(path==='/api/frame-drafts/inspect')return {scan_id:'A',index_sha256:context.index_sha256,draft:body.draft,alignment_id:'AL',requires_review:true};
 return {...review,fusion_parameters:body.fusion_parameters};
});
(async()=>{
 await f.editor.setProject('A');await flush();assert.equal(f.$('frameDraftSave').disabled,false);
 ready(f);f.$('fragmentSourceFrames').value='1152921504606846976,';f.$('fragmentTargetFrames').value='';f.$('fragmentRoi0').value='unfinished';f.$('fragmentRoi1').value='';f.$('fragmentVoxel').value='.8';f.$('fragmentTruncation').value='';f.$('frameDraftLabel').value='Simulated incomplete form';
 const draft=f.editor.draftRecord();assert.equal(draft.source_frames,'1152921504606846976,');assert.equal(draft.roi_fields[0],'unfinished');assert.equal(draft.fusion_fields.truncation_mm,'');assert.ok(!('coordinate_confirmed' in draft));assert.ok(!('review_id' in draft));
 deferSave=true;const saving=f.editor.saveDraft();await flush();f.$('fragmentDecision').value='New text after save request';f.$('fragmentDecision').input();release();await saving;assert.match(f.$('frameDraftStatus').textContent,/尚未保存/);assert.equal(f.submitted.length,0);
 const first=state.drafts[0].id;f.editor.review=f.review;f.$('fragmentCoordinate').checked=true;f.$('frameDraftSelect').value=first;await f.editor.restoreDraft();assert.deepEqual(f.editor.draftRecord(),draft);assert.equal(f.$('fragmentCoordinate').checked,false);assert.equal(f.editor.review,null);assert.equal(f.editor.preset,null);assert.equal(f.$('fragmentRun').disabled,true);await f.editor.run();assert.equal(f.submitted.length,0);
 deferRestore=true;const restoring=f.editor.restoreDraft();await flush();f.$('fragmentTargetFrames').value='changed during restore';f.$('fragmentTargetFrames').input();release();await restoring;assert.equal(f.$('fragmentTargetFrames').value,'changed during restore');assert.match(f.$('frameDraftStatus').textContent,/保留当前编辑/);
 await f.editor.restoreDraft();const blobs=[],create=URL.createObjectURL,revoke=URL.revokeObjectURL;URL.createObjectURL=b=>{blobs.push(b);return 'blob:test';};URL.revokeObjectURL=()=>{};try{f.editor.exportDraft();}finally{URL.createObjectURL=create;URL.revokeObjectURL=revoke;}const file=JSON.parse(await blobs[0].text());assert.deepEqual(file.draft,draft);assert.equal(file.index_sha256,'a'.repeat(64));
 f.$('fragmentTargetFrames').value='changed';f.$('fragmentTargetFrames').input();f.$('frameDraftFile').files=[{size:100,text:async()=>JSON.stringify(file)}];await f.editor.importDraft();assert.deepEqual(f.editor.draftRecord(),draft);assert.equal(f.$('fragmentCoordinate').checked,false);
 let finish;f.$('frameDraftFile').files=[{size:100,text:()=>new Promise(resolve=>{finish=resolve;})}];const importing=f.editor.importDraft();f.$('fragmentTargetFrames').value='newer import edit';f.$('fragmentTargetFrames').input();finish(JSON.stringify(file));await importing;assert.equal(f.$('fragmentTargetFrames').value,'newer import edit');assert.match(f.$('frameDraftStatus').textContent,/保留当前编辑/);
 ready(f);for(const [id,v] of Object.entries({fragmentVoxel:'.8',fragmentTruncation:'3.2',fragmentEdge:'3',fragmentWeight:'2'}))f.$(id).value=v;await f.editor.preview();assert.equal(f.$('fragmentRun').disabled,false);assert.deepEqual(f.requests.filter(r=>r.path==='/api/fragments/reviews').at(-1).body.fusion_parameters,{voxel_mm:.8,truncation_mm:3.2,edge_threshold_mm:3,weight_threshold:2});assert.match(f.$('fragmentReview').textContent,/体素0.8mm/);
 f.$('fragmentWeight').value='3';f.$('fragmentWeight').input();assert.equal(f.editor.review,null);await f.editor.run();assert.equal(f.submitted.length,0);await f.editor.preview();await f.editor.run();assert.equal(f.submitted.length,1,'only explicit reviewed run submits');
 fail=true;const preserved=f.editor.draftRecord();await f.editor.refreshDrafts();assert.equal(f.$('frameDraftSave').disabled,true);assert.deepEqual(f.editor.draftRecord(),preserved);assert.match(f.$('frameDraftStatus').textContent,/读取草稿失败/);

 let finishRestore;const switching=setup((path,body,context)=>{
  const b=path.endsWith('scan=B'),index=b?'f'.repeat(64):context.index_sha256;
  if(path.startsWith('/api/fragments/context'))return {...context,scan_id:b?'B':'A',index_sha256:index};
  if(path.includes('draft_id='))return new Promise(resolve=>{finishRestore=()=>resolve({scan_id:'A',index_sha256:context.index_sha256,state_sha256:'snapshot',drafts:[{id:'one',label:'old A',created_at:'2026-10-25T00:00:00Z',available:true}],draft,alignment_id:'AL'});});
  return {scan_id:b?'B':'A',index_sha256:index,state_sha256:'snapshot',drafts:b?[]:[{id:'one',label:'old A',created_at:'2026-10-25T00:00:00Z',available:true}]};
 });
 await switching.editor.setProject('A');await flush();switching.$('frameDraftSelect').value='one';const oldRestore=switching.editor.restoreDraft();await flush();await switching.editor.setProject('B');finishRestore();await oldRestore;await flush();assert.equal(switching.editor.scan,'B');assert.equal(switching.$('fragmentSourceFrames').value,'');assert.equal(switching.editor.draftBusy,false);
 await switching.editor.setProject('A');await flush();let finishOldFile;switching.$('frameDraftFile').files=[{size:100,text:()=>new Promise(resolve=>{finishOldFile=resolve;})}];const oldFile=switching.editor.importDraft();await switching.editor.setProject('B');switching.$('frameDraftFile').files=[{size:100,text:async()=>''}];switching.$('frameDraftFile').value='new-B-file';finishOldFile(JSON.stringify(file));await oldFile;assert.equal(switching.$('frameDraftFile').value,'new-B-file');
 await f.editor.setProject(null);assert.equal(f.$('frameDraftExport').disabled,true);assert.equal(f.$('fragmentRun').disabled,true);
 console.log(JSON.stringify({real_frame_editor_controller:true,partial_roi_and_settings_text_preserved:true,large_original_ids_preserved:true,restoration_clears_confirmation_preset_and_review:true,old_save_restore_and_import_replies_do_not_overwrite_edits:true,portable_draft_round_trip:true,reviewed_settings_in_request_and_summary:true,parameter_edit_invalidates_ready_review:true,no_implicit_job:true,actual_browser_gpu:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
