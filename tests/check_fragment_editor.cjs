/* Real frame editor controller; simulated DOM/requests, no browser/GPU claim. */
'use strict';
const assert=require('assert/strict'),{FragmentEditor}=require('../web/studio/fragment_editor.js');
class Element{
 constructor(){this.value='';this.checked=false;this.disabled=false;this.textContent='';this.children=[];this.listeners={};}
 append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}input(){for(const fn of this.listeners.input||[])fn();}
}
function setup(apiOverride){
 const elements={},$=id=>elements[id]??=new Element(),requests=[],submitted=[],notifications=[];
 const context={scan_id:'A',index_sha256:'a'.repeat(64),frame_count:3,frames:[{ordinal:1,frame_id:'0',depth_present:true,optimized_pose_present:true},{ordinal:2,frame_id:'8',depth_present:true,optimized_pose_present:false},{ordinal:3,frame_id:'1152921504606846976',depth_present:true,optimized_pose_present:true}],
  alignments:[{id:'AL',label:'verified',sha256:'b'.repeat(64),candidates:['manual_landmarks'],source:{label:'moving'},target:{label:'fixed'}}],
  presets:[{id:'P',label:'recorded frames',sha256:'c'.repeat(64),alignment_ids:['AL'],source_text:'1152921504606846976',target_text:'0',source_basis:'recorded source basis',target_basis:'recorded target basis',roi:[[0,0,1],[10,10,20]]}]};
 const review={id:'R',plan_sha256:'d'.repeat(64),review_sha256:'e'.repeat(64),summary:{target_frames:1,source_frames:1,selected_frames:2,unselected_frames:1,valid_saved_depth_observations_before_roi:8,pinned_files:12},source_frame_ids:['1152921504606846976'],target_frame_ids:['0'],roi:[[0,0,1],[10,10,20]]};
 const api=async(path,body)=>{requests.push({path,body});if(apiOverride)return apiOverride(path,body,context,review);return path.startsWith('/api/fragments/context')?context:review;};
 const editor=new FragmentEditor({api,submit:async request=>{submitted.push(request);return {id:'JOB'};},notify:(...args)=>notifications.push(args),document:{getElementById:$,createElement:()=>new Element()}});
 return {editor,$,context,review,requests,submitted,notifications};
}
function ready(f){f.$('fragmentPreset').value='P';f.editor.applyPreset();f.$('fragmentDecision').value='Scripted controller check, not human geometry validation';f.$('fragmentCoordinate').checked=true;}
(async()=>{
 const f=setup();await f.editor.setProject('A');assert.equal(f.$('fragmentRun').disabled,true);assert.equal(f.$('fragmentSourceFrames').value,'','no inferred ownership');assert.equal(f.$('fragmentFrameRows').children[2].children[1].textContent,'1152921504606846976','large IDs remain strings');
 f.$('fragmentPreset').value='P';f.editor.applyPreset();assert.equal(f.$('fragmentSourceFrames').value,'1152921504606846976');assert.equal(f.$('fragmentCoordinate').checked,false);assert.equal(f.$('fragmentDecision').value,'');
 await f.editor.preview();assert.equal(f.requests.filter(x=>x.body).length,0,'confirmation is explicit');assert.equal(f.$('fragmentRun').disabled,true);
 ready(f);await f.editor.preview();assert.equal(f.$('fragmentRun').disabled,false);assert.match(f.$('fragmentReview').textContent,/固定 1/);assert.equal(f.requests.at(-1).body.source_frames,'1152921504606846976');
 f.$('fragmentSourceFrames').value='8';f.$('fragmentSourceFrames').input();assert.equal(f.editor.review,null);assert.equal(f.editor.preset,null);assert.equal(f.$('fragmentRun').disabled,true);await f.editor.run();assert.equal(f.submitted.length,0,'edited form cannot execute the prior review');
 ready(f);await f.editor.preview();await f.editor.run();assert.deepEqual(f.submitted[0],{kind:'fragment_fusion',review_id:'R',plan_sha256:'d'.repeat(64),review_sha256:'e'.repeat(64)});assert.equal(f.$('fragmentRun').disabled,true);
 let resolveReview;
 const stale=setup((path,body,context,review)=>path.includes('/context')?context:new Promise(resolve=>{resolveReview=()=>resolve(review);}));
 await stale.editor.setProject('A');ready(stale);const pending=stale.editor.preview();stale.$('fragmentDecision').value='New decision while full payload check is running';stale.$('fragmentDecision').input();resolveReview();await pending;
 assert.equal(stale.editor.review,null);assert.equal(stale.$('fragmentRun').disabled,true);assert.match(stale.$('fragmentStatus').textContent,/输入已改变/);
 let resolveA;
 const switched=setup((path,body,context)=>path.endsWith('scan=A')?new Promise(resolve=>{resolveA=()=>resolve(context);}):({...context,scan_id:'B',alignments:[]}));
 const a=switched.editor.setProject('A');await switched.editor.setProject('B');resolveA();await a;assert.equal(switched.editor.scan,'B');assert.equal(switched.editor.context.scan_id,'B');assert.equal(switched.$('fragmentAlignment').value,'');
 const refreshed=setup();await refreshed.editor.setProject('A');ready(refreshed);await refreshed.editor.setProject('A');assert.equal(refreshed.$('fragmentSourceFrames').value,'1152921504606846976','same revision keeps the draft');assert.equal(refreshed.$('fragmentPreset').value,'P');
 refreshed.editor.api=async()=>({...refreshed.context,index_sha256:'f'.repeat(64)});await refreshed.editor.setProject('A');assert.equal(refreshed.$('fragmentSourceFrames').value,'','changed index clears old ownership');assert.equal(refreshed.$('fragmentCoordinate').checked,false);
 await f.editor.setProject(null);assert.equal(f.$('fragmentPreview').disabled,true);assert.equal(f.$('fragmentRun').disabled,true);
 console.log(JSON.stringify({actual_fragment_editor_controller:true,explicit_preset_application:true,original_64bit_ids_as_text:true,edit_invalidates_review:true,inflight_edit_discards_old_review:true,project_switch_discards_old_context:true,index_revision_change_clears_old_binding:true,same_revision_refresh_preserves_draft:true,submitted_plan_and_record_pins:true,actual_browser_verified:false}));
})().catch(error=>{console.error(error);process.exitCode=1;});
