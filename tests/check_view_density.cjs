// Actual generated report controller with a simulated DOM. No browser/GPU claim.
'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8'),raw=html.match(/<script id="view-density-data" type="application\/json">([\s\S]*?)<\/script>/);assert.ok(raw);const data=JSON.parse(raw[1]);
class Element{constructor(){this.children=[];this.value='';this.textContent='';this.style={};}append(...items){this.children.push(...items);}replaceChildren(...items){this.children=items;}}
const elements={},$=id=>elements[id]??=new Element();$('view-density-data').textContent=raw[1];$('tolerance').value='0';$('stride').value='1';$('population').value='frozen_common';
vm.runInNewContext(html.match(/<script>([\s\S]*?)<\/script>/)[1],{document:{getElementById:$,createElement:()=>new Element()},JSON,Math,Number,String});
assert.equal($('edge').children.length,7);assert.equal($('rows').children.length,4);assert.match($('facts').textContent,/正反方向/);
let renders=0;
for(let ei=0;ei<data.edges.length;ei++)for(const stride of [1,2,4,8]){
 $('edge').value=String(ei);$('stride').value=String(stride);$('stride').onchange();const edge=data.edges[ei],profiles=edge.directions.map(d=>d.profiles.filter(p=>p.stride===stride)),phases=Math.max(...profiles.map(p=>p.length));assert.equal($('phase').children.length,phases);
 for(let phase=0;phase<phases;phase++)for(let tolerance=0;tolerance<2;tolerance++)for(const population of ['all','frozen_common','current_common']){
  $('phase').value=String(phase);$('tolerance').value=String(tolerance);$('population').value=population;$('phase').onchange();renders++;
  const present=profiles.map(p=>p.find(p=>p.phase===phase)).filter(Boolean);assert.equal($('rows').children.length,present.length*2);assert.equal($('phases').children.length,profiles.reduce((n,p)=>n+p.length,0));
  const expected=present.flatMap(p=>p.thresholds[tolerance].variants.map(v=>v[population]));
  for(let i=0;i<expected.length;i++){
   const row=expected[i],cells=$('rows').children[i].children;assert.equal(cells.length,8);assert.equal(cells[3].textContent,row.points+' / '+row.observed_in_three);assert.ok(cells[4].textContent.startsWith(row.support+' / '+row.points));assert.ok(cells[5].textContent.startsWith(row.conflict+' / '+row.points));
   for(const j of [4,5]){const width=parseFloat(cells[j].children[0].style.width);assert.ok(Number.isFinite(width)&&width>=0&&width<=100);}
   assert.equal(row.supported_only+row.mixed+row.conflict_only+row.inconclusive,row.points);assert.ok(row.mixed<=row.support&&row.mixed<=row.conflict);
  }
 }
}
const edge=data.edges.find(e=>e.source===3),forward=edge.directions[0].profiles[0].thresholds[0].variants.map(v=>v.frozen_common),reverse=edge.directions[1].profiles[0].thresholds[0].variants.map(v=>v.frozen_common);
assert.deepEqual(forward.map(v=>[v.points,v.conflict]),[[922,55],[922,155]]);assert.deepEqual(reverse.map(v=>[v.points,v.conflict]),[[2428,1435],[2428,690]]);assert.equal(data.exact_old_count_checks,168);
console.log(JSON.stringify({actual_report_controller_simulated_dom:true,edges:7,all_threshold_phase_population_renders:renders,directional_conflict_asymmetry_preserved:true,missing_phase_does_not_hide_other_phase_evidence:true,fixed_and_changing_denominators_explicit:true,gpu_verified:false}));
