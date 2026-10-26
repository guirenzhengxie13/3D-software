// Frozen factorial report and embedded shared viewers; simulated DOM, no GPU proof.
'use strict';const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto'),assert=require('assert/strict');
(async()=>{const file=process.argv[2],url=process.argv[3];let html=fs.readFileSync(file,'utf8');if(url){const response=await fetch(url);assert.equal(response.status,200);const actual=await response.text();assert.equal(actual,html);html=actual;}
const raw=html.match(/<script id="factorial-data" type="application\/json">([\s\S]*?)<\/script>/);assert.ok(raw);const data=JSON.parse(raw[1]);
class Element{constructor(){this.value='';this.textContent='';this.children=[];}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}}
const elements={},$=id=>elements[id]??=new Element();$('factorial-data').textContent=raw[1];$('arm').value='0';$('comparison').value='0';vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],{document:{getElementById:$,createElement:()=>new Element()},JSON,Number,String});
let combinations=0,viewers=0,parsedScripts=0,previewPoints=0;
for(let ai=0;ai<data.arms.length;ai++)for(let ci=0;ci<4;ci++){
 $('arm').value=String(ai);$('comparison').value=String(ci);$('comparison').onchange();const arm=data.arms[ai],c=arm.comparisons[ci];combinations++;
 assert.equal($('view').src,c.page);assert.equal($('external').href,c.page);assert.equal($('matrix').children.length,2);assert.equal($('distances').children.length,2);assert.equal($('critical').children.length,2);
 const a=data.configs.find(x=>x.key===c.left),b=data.configs.find(x=>x.key===c.right);assert.deepEqual(Object.keys(a.settings).filter(k=>a.settings[k]!==b.settings[k]),[c.parameter]);
 assert.equal($('matrix').children[0].children[1].textContent,String(arm.counts['v06-t24']));assert.equal($('matrix').children[1].children[2].textContent,String(arm.counts['v08-t32']));
 const difference=(arm.counts['v08-t32']-arm.counts['v08-t24'])-(arm.counts['v06-t32']-arm.counts['v06-t24']);assert.equal(difference,arm.count_difference_of_differences);
 for(const d of [c.left_to_right,c.right_to_left])assert.ok(d.maximum_mm>=d.p95_mm&&d.p95_mm>=d.median_mm&&d.within_1mm_fraction>=0&&d.within_1mm_fraction<=1);
 for(let t=0;t<2;t++)for(let k=0;k<4;k++)assert.equal($('critical').children[t].children[k+1].textContent,arm.critical_locations[t].nearest[k].nearest_mm.toFixed(4)+' mm');
 const page=fs.readFileSync(path.join(path.dirname(file),c.page),'utf8'),payload=JSON.parse(page.match(/<script id="comparison-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);viewers++;
 assert.equal(payload.unit,'mm');assert.equal(payload.clouds[0].originalPoints,c.left_points);assert.equal(payload.clouds[1].originalPoints,c.right_points);
 for(const cloud of payload.clouds){const ids=Buffer.from(cloud.ids,'base64'),xyz=Buffer.from(cloud.xyz,'base64');assert.equal(ids.length,cloud.displayPoints*4);assert.equal(xyz.length,cloud.displayPoints*12);let unique=new Set();for(let k=0;k<ids.length/4;k++){const id=ids.readUInt32LE(k*4);assert.ok(id<cloud.originalPoints);unique.add(id);for(let j=0;j<3;j++)assert.ok(Number.isFinite(xyz.readFloatLE(k*12+j*4)));}assert.equal(unique.size,cloud.displayPoints);previewPoints+=cloud.displayPoints;}
 for(const m of page.matchAll(/<script>([\s\S]*?)<\/script>/g)){new vm.Script(m[1]);parsedScripts++;}
}
assert.equal(data.selected_frames,114);assert.equal(data.same_applied_pose_arrays,true);assert.equal(data.source_payload_files_per_arm,229);
const saved=data.arms.find(a=>a.arm==='saved'),p=saved.critical_locations.find(t=>t.reference_variant==='coarse');assert.equal(p.reference_vertex_id,27957);
console.log(JSON.stringify({actual_generated_factorial_controller_simulated_dom:true,one_parameter_comparisons:combinations,shared_viewer_pages:viewers,embedded_scripts_parse:parsedScripts,preview_original_points_verified:previewPoints,source_payloads_per_arm:229,same_applied_poses:true,served_http_matches_disk:Boolean(url),actual_browser_gpu:false}));
})().catch(e=>{console.error(e);process.exitCode=1;});
