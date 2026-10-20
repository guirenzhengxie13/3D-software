'use strict';
const assert=require('assert/strict');
const fs=require('fs');
const math=require('../web/landmark-workbench/registration_math.js');
const fixture=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
for(const row of fixture){
  const result=math.solveRigid(row.source,row.target);
  const error=Math.max(...result.matrix.flat().map((x,i)=>Math.abs(x-row.expected.flat()[i])));
  assert.ok(error<1e-7,`Python SVD / browser quaternion mismatch ${error}`);
  assert.ok(Math.abs(result.rmse-row.rmse)<1e-8);
}
assert.throws(()=>math.solveRigid([[0,0,0],[1,0,0],[2,0,0]],[[0,0,1],[1,0,1],[2,0,1]]),/collinear/);
assert.throws(()=>math.solveRigid([[NaN,0,0],[0,1,0],[0,0,1]],[[1,0,0],[0,1,0],[0,0,1]]),/finite/);
const eye=Float32Array.from([1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]);
const picked=math.pickPoint(Float32Array.from([0,0,.8,0,0,-.5,0,0,2]),eye,100,100,50,50);
assert.equal(picked.index,1,'front visible point wins over an overlapping rear point');
assert.equal(math.pickPoint(Float32Array.from([2,0,0]),eye,100,100,50,50),null);
const tetra=[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],mirrored=tetra.map(([x,y,z])=>[-x,y,z]);
assert.ok(math.solveRigid(tetra,mirrored).rmse>.1,'a mirrored tetrahedron cannot be fitted by silently reflecting');
console.log(JSON.stringify({python_svd_cases:fixture.length,geometry_and_picking_controls:5,passed:true}));
