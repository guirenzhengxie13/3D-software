// Actual generated parameter-response controller; simulated DOM, no GPU claim.
'use strict';const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
const file=process.argv[2],html=fs.readFileSync(file,'utf8'),raw=html.match(/<script id="setting-data" type="application\/json">([\s\S]*?)<\/script>/);assert.ok(raw);const data=JSON.parse(raw[1]);
class Element{constructor(){this.value='';this.children=[];this.textContent='';}append(...items){this.children.push(...items);}}
const elements={},$=id=>elements[id]??=new Element();$('setting-data').textContent=raw[1];$('arm').value='0';$('mode').value='surface';const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];vm.runInNewContext(script,{document:{getElementById:$,createElement:()=>new Element()},JSON,Math,Number,String});
assert.equal($('rows').children.length,4);let pages=0,scripts=0;
for(let arm=0;arm<2;arm++)for(const mode of ['surface','distance']){
 $('arm').value=String(arm);$('mode').value=mode;$('mode').onchange();const expected=data.arms[arm].pages[mode];assert.equal($('comparison').src,expected);assert.equal($('external').href,expected);const target=path.join(path.dirname(file),expected);assert.ok(fs.existsSync(target));pages++;
 const text=fs.readFileSync(target,'utf8');for(const match of text.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)){if(!match[0].startsWith('<script>'))continue;new vm.Script(match[1]);scripts++;}
}
for(const arm of data.arms){assert.equal(arm.historical_default_bidirectional_max_mm,0);assert.equal(arm.same_applied_pose_arrays,true);assert.equal(arm.same_original_payload_files,229);for(const key of ['fine_to_coarse','coarse_to_fine']){const d=arm[key];assert.ok(d.maximum_mm>=d.p95_mm&&d.p95_mm>=d.median_mm);for(let i=1;i<d.within.length;i++)assert.ok(d.within[i].fraction>=d.within[i-1].fraction);}}
assert.deepEqual(data.changed_parameters,['voxel_mm','truncation_mm']);assert.equal(data.selected_frames,114);assert.match($('provenance').textContent,/不是物理误差/);
console.log(JSON.stringify({actual_generated_controller_simulated_dom:true,selection_combinations:4,referenced_pages_exist:pages,embedded_executable_scripts_parse:scripts,full_source_payloads_and_applied_poses_equal:true,historical_default_reproduced_as_point_set:true,not_physical_accuracy:true,actual_browser_gpu:false}));
