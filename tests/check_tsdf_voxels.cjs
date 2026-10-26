// Actual generated voxel controller; simulated DOM/SVG, no browser or GPU claim.
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert/strict');
(async()=>{
const file=process.argv[2],servedUrl=process.argv[3];let html=fs.readFileSync(file,'utf8');if(servedUrl){const response=await fetch(servedUrl);assert.equal(response.status,200);const actual=await response.text();assert.equal(actual,html,'served page bytes match frozen report');html=actual;}const raw=html.match(/<script id="voxel-data" type="application\/json">([\s\S]*?)<\/script>/);
assert.ok(raw,'generated data required');const data=JSON.parse(raw[1]);
class Element{constructor(){this.value='';this.textContent='';this.children=[];this.attributes={};this.disabled=false;}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}setAttribute(k,v){this.attributes[k]=String(v);}}
const elements={},$=id=>elements[id]??=new Element();$('voxel-data').textContent=raw[1];
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];vm.runInNewContext(script,{document:{getElementById:$,createElement:()=>new Element(),createElementNS:()=>new Element()},JSON,Math,Number,String,Object});
let snapshots=0,edges=0;
for(let ci=0;ci<data.cases.length;ci++){
 const c=data.cases[ci];$('case').value=String(ci);$('case').onchange();
 assert.equal($('points').textContent,c.replay_points.toLocaleString());assert.equal(c.full_pointset_bidirectional_max_mm,0);assert.equal(c.observed_frames,114);
 for(let ti=0;ti<c.targets.length;ti++){
  const t=c.targets[ti];$('target').value=String(ti);$('target').onchange();
  assert.ok($('location').textContent.includes(t.reference_mm.map(v=>v.toFixed(4)).join(', ')));
  for(let ei=0;ei<t.edges.length;ei++){
   const e=t.edges[ei];$('edge').value=String(ei);$('edge').onchange();edges++;
   for(const r of e.timeline){
    $('step').value=String(r.step);$('step').oninput();snapshots++;
    const gate=r.allocated&&r.weights.every(w=>w>c.settings.weight_threshold),opposite=r.allocated&&r.tsdf.every(v=>v!==null)&&r.tsdf[0]*r.tsdf[1]<0;
    assert.equal(r.strict_weight_gate,gate);assert.equal(r.opposite_sign,opposite);assert.equal(r.point_extractable,gate&&opposite);
    assert.equal($('rows').children.length,2);for(let j=0;j<2;j++)assert.equal($('rows').children[j].children[3].textContent,String(r.weights[j]));
    assert.equal($('gate').className,gate&&opposite?'pass':'fail');assert.equal($('previous').disabled,r.step===0);assert.equal($('next').disabled,r.step===114);
    if(r.step>0)assert.ok($('position').textContent.endsWith('原帧ID '+r.frame_id));
    for(const chart of ['weights','tsdf','lattice'])for(const shape of $(chart).children)for(const value of Object.values(shape.attributes))assert.ok(!/NaN|Infinity/.test(value));
   }
   $('step').value='0';$('step').oninput();$('next').onclick();assert.ok($('position').textContent.startsWith('1 /'));$('previous').onclick();assert.ok($('position').textContent.includes('尚未积分'));
  }
 }
}
// The same physical query location retains its reference identity when switching grid.
$('case').value=String(data.cases.findIndex(c=>c.case==='coarse-saved'));$('case').onchange();$('target').value='1';$('target').onchange();assert.ok($('gate').textContent.startsWith('按当前状态可提取'));assert.equal($('rows').children[0].children[3].textContent,'6');assert.equal($('rows').children[1].children[3].textContent,'4');
$('peer').onclick();assert.equal(data.cases[Number($('case').value)].case,'fine-saved');assert.ok($('neighborhood').textContent.includes('14 条虽异号但权重不足'));assert.ok($('gate').textContent.startsWith('按当前状态不可提取'));assert.ok($('location').textContent.includes('不在本配置'));
for(const match of html.matchAll(/href="([^"#]+)"/g)){const href=match[1];if(href.startsWith('http')||href==='/')continue;assert.ok(fs.existsSync(path.resolve(path.dirname(file),href)),href);}
console.log(JSON.stringify({actual_generated_controller_simulated_dom_svg:true,cases:data.cases.length,selected_edges:edges,edge_snapshot_checks:snapshots,strict_weight_gate_and_sign_verified:true,original_frame_ids_retained:true,cross_grid_query_location_retained:true,local_report_links_exist:true,served_http_matches_disk:Boolean(servedUrl),actual_browser_gpu:false}));

})().catch(error=>{console.error(error);process.exitCode=1;});
