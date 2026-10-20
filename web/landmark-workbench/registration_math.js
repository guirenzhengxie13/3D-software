/* Deterministic rigid landmark fitting and visible-point selection.
 * Matrices exposed here are row-major. No scaling or reflection is fitted.
 */
(function(root) {
  'use strict';
  const identity = () => [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]];
  function apply(matrix,point) {
    return [0,1,2].map(i => matrix[i][0]*point[0]+matrix[i][1]*point[1]+matrix[i][2]*point[2]+matrix[i][3]);
  }
  function eigenSymmetric(input) {
    const n=input.length,a=input.map(row=>row.slice()),v=Array.from({length:n},(_,i)=>Array.from({length:n},(_,j)=>Number(i===j)));
    for(let iteration=0;iteration<100;iteration++) {
      let p=0,q=1,largest=0,scale=0;
      for(let i=0;i<n;i++) for(let j=0;j<n;j++) {
        scale=Math.max(scale,Math.abs(a[i][j]));
        if(i<j&&Math.abs(a[i][j])>largest){largest=Math.abs(a[i][j]);p=i;q=j;}
      }
      if(largest<=Math.max(scale,1e-30)*1e-14)break;
      const tau=(a[q][q]-a[p][p])/(2*a[p][q]);
      const t=(tau>=0?1:-1)/(Math.abs(tau)+Math.sqrt(1+tau*tau)),c=1/Math.sqrt(1+t*t),s=t*c;
      const off=a[p][q];a[p][p]-=t*off;a[q][q]+=t*off;a[p][q]=a[q][p]=0;
      for(let k=0;k<n;k++) if(k!==p&&k!==q){const x=a[k][p],y=a[k][q];a[k][p]=a[p][k]=c*x-s*y;a[k][q]=a[q][k]=s*x+c*y;}
      for(let k=0;k<n;k++){const x=v[k][p],y=v[k][q];v[k][p]=c*x-s*y;v[k][q]=s*x+c*y;}
    }
    return {values:a.map((row,i)=>row[i]),vectors:v};
  }
  function pointArray(value) {
    if(!Array.isArray(value)||value.length<3||value.some(row=>!Array.isArray(row)||row.length!==3||row.some(x=>typeof x!=='number'||!Number.isFinite(x))))
      throw new Error('At least three finite XYZ correspondences are required');
  }
  function centered(points) {
    const mean=[0,0,0];for(const row of points)for(let i=0;i<3;i++)mean[i]+=row[i]/points.length;
    const rows=points.map(row=>row.map((x,i)=>x-mean[i]));
    const covariance=Array.from({length:3},()=>[0,0,0]);
    for(const row of rows)for(let i=0;i<3;i++)for(let j=0;j<3;j++)covariance[i][j]+=row[i]*row[j]/points.length;
    const values=eigenSymmetric(covariance).values.sort((a,b)=>b-a);
    if(values[0]<=1e-20||values[1]<=values[0]*1e-6)throw new Error('Correspondences are collinear or too concentrated; pick spread-out points');
    return {mean,rows,condition:values[1]/values[0],span:Math.sqrt(values.reduce((a,b)=>a+b,0))};
  }
  function solveRigid(source,target) {
    pointArray(source);pointArray(target);
    if(source.length!==target.length)throw new Error('Source and target pair counts differ');
    const a=centered(source),b=centered(target),S=Array.from({length:3},()=>[0,0,0]);
    for(let k=0;k<source.length;k++)for(let i=0;i<3;i++)for(let j=0;j<3;j++)S[i][j]+=a.rows[k][i]*b.rows[k][j];
    const [x,y,z]=S,trace=x[0]+y[1]+z[2];
    const horn=[[trace,y[2]-z[1],z[0]-x[2],x[1]-y[0]],
      [y[2]-z[1],x[0]-y[1]-z[2],x[1]+y[0],x[2]+z[0]],
      [z[0]-x[2],x[1]+y[0],-x[0]+y[1]-z[2],y[2]+z[1]],
      [x[1]-y[0],x[2]+z[0],y[2]+z[1],-x[0]-y[1]+z[2]]];
    const eigen=eigenSymmetric(horn),largest=eigen.values.indexOf(Math.max(...eigen.values));
    let quaternion=eigen.vectors.map(row=>row[largest]);const length=Math.hypot(...quaternion);quaternion=quaternion.map(x=>x/length);
    const [w,i,j,k]=quaternion;
    const R=[[1-2*(j*j+k*k),2*(i*j-w*k),2*(i*k+w*j)],
      [2*(i*j+w*k),1-2*(i*i+k*k),2*(j*k-w*i)],
      [2*(i*k-w*j),2*(j*k+w*i),1-2*(i*i+j*j)]];
    const matrix=identity();for(let row=0;row<3;row++){for(let col=0;col<3;col++)matrix[row][col]=R[row][col];matrix[row][3]=b.mean[row]-R[row].reduce((n,x,col)=>n+x*a.mean[col],0);}
    const residuals=source.map((point,index)=>Math.hypot(...apply(matrix,point).map((x,j)=>x-target[index][j])));
    const rmse=Math.sqrt(residuals.reduce((n,x)=>n+x*x,0)/residuals.length);
    if(!Number.isFinite(rmse)||matrix.some(row=>row.some(x=>!Number.isFinite(x))))throw new Error('Nonfinite rigid fit');
    return {matrix,residuals,rmse,maxResidual:Math.max(...residuals),sourceConditionRatio:a.condition,targetConditionRatio:b.condition,spanRatio:b.span/a.span};
  }
  function project(point,matrix,width,height) {
    const [x,y,z]=point,w=matrix[3]*x+matrix[7]*y+matrix[11]*z+matrix[15];
    if(w<=0)return null;
    const p=[(matrix[0]*x+matrix[4]*y+matrix[8]*z+matrix[12])/w,(matrix[1]*x+matrix[5]*y+matrix[9]*z+matrix[13])/w,(matrix[2]*x+matrix[6]*y+matrix[10]*z+matrix[14])/w];
    if(p.some(v=>v < -1||v > 1))return null;
    return [(p[0]+1)*width/2,(1-p[1])*height/2,p[2]];
  }
  function pickPoint(xyz,matrix,width,height,x,y,radius=9) {
    const buckets=new Map();
    for(let index=0;index<xyz.length/3;index++) {
      const point=project([xyz[index*3],xyz[index*3+1],xyz[index*3+2]],matrix,width,height);if(!point)continue;
      const d=(point[0]-x)**2+(point[1]-y)**2;if(d>radius*radius)continue;
      const key=Math.round(point[0])+','+Math.round(point[1]),old=buckets.get(key);
      if(!old||point[2]<old.depth)buckets.set(key,{index,distanceSquared:d,depth:point[2]});
    }
    let best=null;for(const value of buckets.values())if(!best||value.distanceSquared<best.distanceSquared||(value.distanceSquared===best.distanceSquared&&value.depth<best.depth))best=value;
    return best;
  }
  const api={identity,apply,solveRigid,project,pickPoint};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.RegistrationMath=api;
})(typeof globalThis!=='undefined'?globalThis:this);
