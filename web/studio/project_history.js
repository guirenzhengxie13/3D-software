/* Project result snapshots; undo switches model versions without editing geometry. */
(function(root){
 'use strict';
 class ProjectHistoryController{
  constructor({api,selection,apply,notify,document:doc=root.document}){
   this.api=api;this.selection=selection;this.apply=apply;this.notify=notify;this.doc=doc;this.$=id=>doc.getElementById(id);this.scan=null;this.context=null;this.generation=0;this.selectionToken=0;this.busy=false;this.draft=false;
   for(const [id,action] of [['historySave','save'],['historyUndo','undo'],['historyRedo','redo'],['historyRestore','restore']])this.$(id).onclick=()=>this.change(action);
   this.$('historyRefresh').onclick=()=>this.setProject(this.scan,{restore:false});this.$('historyVersion').onchange=()=>{this.detail();this.buttons();};this.buttons();
  }
  element(tag,text){const n=this.doc.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
  status(text){this.$('historyStatus').textContent=text;}
  selectionChanged(){this.selectionToken++;this.draft=true;if(this.context)this.status('当前为临时浏览。工程活动版本保留；保存当前模型组合会创建新版本。');this.buttons();}
  buttons(){const c=this.context,ready=Boolean(c&&!this.busy);let selection=false;try{selection=Boolean(this.selection()?.length);}catch{}this.$('historySave').disabled=!ready||!selection;this.$('historyUndo').disabled=!ready||!c.can_undo;this.$('historyRedo').disabled=!ready||!c.can_redo;this.$('historyRefresh').disabled=!this.scan||this.busy;const version=c?.versions.find(v=>v.id===this.$('historyVersion').value);this.$('historyRestore').disabled=!ready||!version?.available||version.id===c.active;}
  render(){const c=this.context,select=this.$('historyVersion'),previous=select.value;select.replaceChildren();this.$('historyEvents').replaceChildren();
   if(!c){this.$('historyActive').textContent='未选择单一工程';this.$('historyVersionInfo').textContent='';this.buttons();return;}
   this.$('historyActive').textContent=c.active_version?'工程活动版本：'+c.active_version.label:'尚未登记工程版本';
   for(const version of c.versions){const option=this.element('option',version.label+' · '+version.model_labels.join(' + ')+(version.available?'':' · 文件缺失或换版'));option.value=version.id;select.append(option);}
   select.value=c.versions.some(v=>v.id===previous)?previous:c.active||'';
   for(const event of c.events.slice(-20).reverse()){const labels={save:'保存新版本',restore:'切换到已有版本',undo:'撤销版本切换',redo:'重做版本切换'};this.$('historyEvents').append(this.element('li',event.sequence+' · '+labels[event.action]+' · '+event.to_version+' · '+event.at));}
   this.detail();this.buttons();
  }
  detail(){const v=this.context?.versions.find(v=>v.id===this.$('historyVersion').value);this.$('historyVersionInfo').textContent=v?[v.created_at,'版本 '+v.id+' · 父版本 '+(v.parent_id||'无'),v.decision,...v.provenance.map(p=>p.kind==='completed_fragment_fusion'?'重融合任务 '+p.job_id+' · '+(p.saved_control?'原位姿控制':'片段校正候选')+' · '+p.selected_frames+'帧':'目录模型快照；本步骤未推断原帧归属'),...v.problems].join('\n'):'先保存当前已加载的目录模型，建立可返回的起点。';}
  async setProject(scan,{restore=true}={}){
   const same=scan===this.scan;this.scan=scan;const generation=++this.generation,token=this.selectionToken;this.context=null;this.busy=false;if(!same){this.draft=false;this.$('historyLabel').value='';this.$('historyDecision').value='';}this.render();
   if(!scan){this.status('跨工程和浏览器临时PLY暂不登记工程版本。');return {applied:false};}
   this.status('正在读取工程版本与固定文件…');
   try{const context=await this.api('/api/history?scan='+encodeURIComponent(scan));if(generation!==this.generation)return {applied:false};this.context=context;this.render();let applied=false;
    if(restore&&context.active_version?.available&&token===this.selectionToken){applied=Boolean(await this.apply(context.active_version.models,scan));if(generation!==this.generation)return {applied:false};if(applied)this.draft=false;}
    if(context.active_version&&!context.active_version.available)this.status('活动版本文件缺失或换版，保留当前临时浏览；可在版本详情中核对。');
    else this.status(applied?'已按固定SHA恢复工程活动版本。':this.draft?'临时浏览保留，工程活动版本未改变。':'可保存当前模型组合；处理任务完成后需明确选择结果再登记。');this.buttons();return {applied};
   }catch(error){if(generation===this.generation){this.context=null;this.status('读取工程版本失败：'+error.message);this.buttons();}return {applied:false};}
  }
  async change(action){
   if(!this.context||this.busy)return;const generation=this.generation,token=this.selectionToken,c=this.context,scan=this.scan;
   try{const request={scan_id:scan,index_sha256:c.index_sha256,state_sha256:c.state_sha256,action};
    if(action==='save'){request.models=this.selection();request.label=this.$('historyLabel').value.trim();request.decision=this.$('historyDecision').value.trim();if(!request.label||!request.decision)throw Error('请填写版本名称和本次决定说明');}
    if(action==='restore')request.version_id=this.$('historyVersion').value;
    this.busy=true;this.buttons();this.status('正在核对固定文件并保存版本切换…');const result=await this.api('/api/history',request);if(generation!==this.generation)return;
    this.context=result;this.render();let applied=false;if(token===this.selectionToken&&result.active_version?.available)applied=Boolean(await this.apply(result.active_version.models,scan));
    if(generation!==this.generation)return;if(applied){this.draft=false;this.status('版本记录已保存，模型按固定SHA载入；原件和处理结果保留。');}else this.status('工程版本已更新；当前临时浏览保留。可刷新版本记录后重新载入。');
   }catch(error){if(generation===this.generation){this.status('版本操作未完成：'+error.message);this.notify?.(error.message,true);}}
   finally{if(generation===this.generation){this.busy=false;this.buttons();}}
  }
 }
 root.ProjectHistoryController=ProjectHistoryController;if(typeof module!=='undefined'&&module.exports)module.exports={ProjectHistoryController};
})(typeof window!=='undefined'?window:globalThis);
