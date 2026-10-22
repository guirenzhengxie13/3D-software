/* Explicit frame ownership and reviewed fusion inside the engineering workspace. */
(function(root){
 'use strict';
 class FragmentEditor{
  constructor({api,submit,notify,document:doc=root.document}){
   this.api=api;this.submit=submit;this.notify=notify;this.doc=doc;this.$=id=>doc.getElementById(id);this.scan=null;this.context=null;this.revision=0;this.contextVersion=0;this.previewSequence=0;this.previewBusy=false;this.submitting=false;this.review=null;this.preset=null;
   const $=this.$;
   $('fragmentAlignment').onchange=()=>this.chooseAlignment(false);
   $('fragmentCandidate').onchange=()=>this.invalidate(false);
   $('fragmentPreset').onchange=()=>{this.preset=null;this.invalidate(false);this.buttons();};
   $('fragmentApplyPreset').onclick=()=>this.applyPreset();
   $('fragmentPreview').onclick=()=>this.preview();$('fragmentRun').onclick=()=>this.run();
   for(const id of ['fragmentMode','fragmentSourceFrames','fragmentTargetFrames','fragmentSourceBasis','fragmentTargetBasis',...Array.from({length:6},(_,i)=>'fragmentRoi'+i)])$(id).addEventListener('input',()=>this.invalidate(true));
   for(const id of ['fragmentDecision','fragmentCoordinate'])$(id).addEventListener('input',()=>this.invalidate(false));
   this.buttons();
  }
  status(text){this.$('fragmentStatus').textContent=text;}
  invalidate(clearPreset=false){this.revision++;this.review=null;this.$('fragmentReview').textContent='输入更改后需要重新核验，执行只使用已核验的那个版本。';if(clearPreset){this.preset=null;this.$('fragmentPreset').value='';}this.buttons();}
  buttons(){const ready=Boolean(this.context&&this.$('fragmentAlignment').value);this.$('fragmentPreview').disabled=!ready||this.previewBusy||this.submitting;this.$('fragmentRun').disabled=!this.review||this.previewBusy||this.submitting;this.$('fragmentApplyPreset').disabled=!ready||!this.$('fragmentPreset').value||this.previewBusy;}
  element(tag,text){const node=this.doc.createElement(tag);if(text!==undefined)node.textContent=text;return node;}
  options(id,rows,selected=''){const e=this.$(id);e.replaceChildren();for(const row of rows){const option=this.element('option',row.label);option.value=row.id;e.append(option);}e.value=rows.some(r=>r.id===selected)?selected:rows[0]?.id||'';}
  clearFields(){for(const id of ['fragmentSourceFrames','fragmentTargetFrames','fragmentSourceBasis','fragmentTargetBasis','fragmentDecision',...Array.from({length:6},(_,i)=>'fragmentRoi'+i)])this.$(id).value='';this.$('fragmentCoordinate').checked=false;this.$('fragmentMode').value='ordinal_1based';this.preset=null;}
  async setProject(scan){
   const same=scan===this.scan,previous=this.$('fragmentAlignment').value,previousIndex=this.context?.index_sha256,previousAlignment=this.context?.alignments.find(a=>a.id===previous)?.sha256;this.scan=scan;const version=++this.contextVersion;this.previewSequence++;this.previewBusy=false;this.context=null;this.invalidate();if(!same)this.clearFields();
   if(!scan){this.options('fragmentAlignment',[]);this.options('fragmentCandidate',[]);this.options('fragmentPreset',[]);this.$('fragmentFrameRows').replaceChildren();this.status('选择一份扫描工程后，可把已核验的对齐结果绑定到原帧。');this.buttons();return;}
   this.status('正在读取本工程的核验结果与原帧记录…');
   try{const data=await this.api('/api/fragments/context?scan='+encodeURIComponent(scan));if(version!==this.contextVersion)return;this.context=data;
    this.options('fragmentAlignment',data.alignments,same?previous:'');this.chooseAlignment(same&&previous===this.$('fragmentAlignment').value&&previousIndex===data.index_sha256&&previousAlignment===data.alignments.find(a=>a.id===previous)?.sha256);
    this.$('fragmentFrameRows').replaceChildren();let missing=0;
    for(const frame of data.frames){const row=this.element('tr');for(const value of [frame.ordinal,frame.frame_id,frame.depth_present?'存在':'缺失',frame.optimized_pose_present?'存在':'缺失'])row.append(this.element('td',String(value)));this.$('fragmentFrameRows').append(row);if(!frame.depth_present||!frame.optimized_pose_present)missing++;}
    this.$('fragmentFrameCount').textContent=data.frame_count+'条保存记录 · '+missing+'条缺深度或优化位姿（存在性检查）';
    this.status(data.alignments.length?'先选择已核验对齐，明确两片段拥有的原帧，再核验和执行。':'当前工程没有可用核验对齐结果；先在对应点工作区提交会话并等待完成。');
   }catch(error){if(version===this.contextVersion)this.status('读取帧归属上下文失败：'+error.message);}finally{if(version===this.contextVersion)this.buttons();}
  }
  chooseAlignment(preserve){
   const a=this.context?.alignments.find(x=>x.id===this.$('fragmentAlignment').value);if(!preserve)this.clearFields();this.invalidate();
   const prior=this.$('fragmentCandidate').value;this.options('fragmentCandidate',(a?.candidates||[]).map(label=>({id:label,label})),preserve?prior:'');
   const presets=(this.context?.presets||[]).filter(p=>p.alignment_ids.includes(a?.id)),previous=this.$('fragmentPreset').value;this.options('fragmentPreset',[{id:'',label:'可载入先前记录的帧归属…'},...presets],preserve?previous:'');
   this.preset=preserve&&this.preset?presets.find(p=>p.id===this.preset.id&&p.sha256===this.preset.sha256)||null:null;
   this.$('fragmentModels').textContent=a?'固定：'+a.target.label+'\n移动：'+a.source.label:'先选择一份已核验对齐结果。';this.buttons();
  }
  applyPreset(){
   const preset=this.context?.presets.find(p=>p.id===this.$('fragmentPreset').value);if(!preset)return;
   this.$('fragmentMode').value='frame_id';this.$('fragmentTargetFrames').value=preset.target_text;this.$('fragmentSourceFrames').value=preset.source_text;
   this.$('fragmentTargetBasis').value=preset.target_basis;this.$('fragmentSourceBasis').value=preset.source_basis;this.$('fragmentDecision').value='';this.$('fragmentCoordinate').checked=false;
   for(let i=0;i<6;i++)this.$('fragmentRoi'+i).value=preset.roi?String(preset.roi[Math.floor(i/3)][i%3]):'';
   this.preset=preset;this.invalidate(false);this.status('已载入先前帧归属和选区。请核对保存坐标依据，并填写本次选择说明后核验。');
  }
  request(){
   const a=this.context?.alignments.find(x=>x.id===this.$('fragmentAlignment').value);if(!a)throw Error('请选择一份已核验对齐结果');
   if(!this.$('fragmentCoordinate').checked)throw Error('请确认两模型使用原保存扫描毫米坐标');
   for(const id of ['fragmentSourceFrames','fragmentTargetFrames','fragmentSourceBasis','fragmentTargetBasis','fragmentDecision'])if(!this.$(id).value.trim())throw Error('请填写两片段的帧范围、归属依据与本次选择说明');
   const values=Array.from({length:6},(_,i)=>this.$('fragmentRoi'+i).value.trim());let roi=null;
   if(values.some(Boolean)){if(values.some(x=>!x))throw Error('原坐标选区需完整填写6个边界值，或全部留空');const numbers=values.map(Number);if(!numbers.every(Number.isFinite))throw Error('选区边界必须为有限毫米数值');roi=[numbers.slice(0,3),numbers.slice(3)];}
   const payload={scan_id:this.scan,index_sha256:this.context.index_sha256,alignment_id:a.id,alignment_sha256:a.sha256,
    candidate:this.$('fragmentCandidate').value,mode:this.$('fragmentMode').value,
    source_frames:this.$('fragmentSourceFrames').value,target_frames:this.$('fragmentTargetFrames').value,
    source_basis:this.$('fragmentSourceBasis').value,target_basis:this.$('fragmentTargetBasis').value,
    decision:this.$('fragmentDecision').value,coordinate_confirmed:this.$('fragmentCoordinate').checked,roi};
   if(this.preset){payload.preset_id=this.preset.id;payload.preset_sha256=this.preset.sha256;}return payload;
  }
  async preview(){
   if(this.previewBusy)return;const version=this.contextVersion,revision=this.revision,sequence=++this.previewSequence;
   this.review=null;this.buttons();
   try{const request=this.request();this.previewBusy=true;this.buttons();this.status('正在实际核验原模型、选中深度与优化位姿…');
    const review=await this.api('/api/fragments/reviews',request);if(version!==this.contextVersion||sequence!==this.previewSequence)return;
    if(revision!==this.revision){this.status('输入已改变，刚才的核验记录已保存；请核验当前输入。');return;}
    this.review=review;const s=review.summary,show=ids=>ids.slice(0,20).join(', ')+(ids.length>20?' …（完整编号已记录）':'');
    this.$('fragmentReview').textContent=`已实际核验：固定 ${s.target_frames} + 移动 ${s.source_frames} = ${s.selected_frames} 帧；未选择 ${s.unselected_frames} 帧。
选区前有效深度观测 ${s.valid_saved_depth_observations_before_roi.toLocaleString()}；固定 ${s.pinned_files} 份文件版本。
固定原帧：${show(review.target_frame_ids)}
移动原帧：${show(review.source_frame_ids)}
${review.roi?'原保存坐标ROI已固定。':'未设置ROI，使用选中帧的全部保存有效深度。'}
两组使用同一原始像素，体素0.6mm、截断2.4mm、提取权重3。核验版本 ${review.id}。`;
    this.status('核验通过。可按此版本运行原位姿控制组与片段校正组，结果将另存。');
   }catch(error){if(version===this.contextVersion){this.status('核验未通过：'+error.message);this.notify?.(error.message,true);}}
   finally{if(sequence===this.previewSequence){this.previewBusy=false;this.buttons();}}
  }
  async run(){
   const review=this.review;if(!review||this.submitting)return;const version=this.contextVersion;this.submitting=true;this.buttons();
   try{const job=await this.submit({kind:'fragment_fusion',review_id:review.id,plan_sha256:review.plan_sha256,review_sha256:review.review_sha256});if(job&&version===this.contextVersion){this.review=null;this.status('已提交两组重融合任务 '+job.id+'，可在处理任务中查看日志和结果。');}}
   finally{this.submitting=false;this.buttons();}
  }
 }
 root.FragmentEditor=FragmentEditor;if(typeof module!=='undefined'&&module.exports)module.exports={FragmentEditor};
})(typeof window!=='undefined'?window:globalThis);
