/* Local point-cloud import; explicit units, bounded preview, no upload. */
(function(root){
 'use strict';
 const types={char:[1,'getInt8'],int8:[1,'getInt8'],uchar:[1,'getUint8'],uint8:[1,'getUint8'],short:[2,'getInt16'],int16:[2,'getInt16'],ushort:[2,'getUint16'],uint16:[2,'getUint16'],int:[4,'getInt32'],int32:[4,'getInt32'],uint:[4,'getUint32'],uint32:[4,'getUint32'],float:[4,'getFloat32'],float32:[4,'getFloat32'],double:[8,'getFloat64'],float64:[8,'getFloat64']};
 function parse(buffer,unit='mm',budget=40000){
  if(!['mm','m'].includes(unit))throw Error('请明确 PLY 单位');if(buffer.byteLength>512*1024*1024)throw Error('本地导入限制为512MiB，请先通过项目后端构建空间缓存');
  const beginning=new TextDecoder('ascii').decode(buffer.slice(0,Math.min(buffer.byteLength,65536))),end=/end_header\r?\n/.exec(beginning);if(!end||!/^ply\r?\n/.test(beginning))throw Error('没有找到有效 PLY 头');
  const header=beginning.slice(0,end.index),offset=end.index+end[0].length;let format,count=0,current,props=[],stride=0,seenVertex=false;
  for(const line of header.split(/\r?\n/)){const p=line.trim().split(/\s+/);if(p[0]==='format')format=p[1];if(p[0]==='element'){current=p[1];if(current==='vertex'){if(seenVertex)throw Error('重复 vertex 元素');seenVertex=true;count=Number(p[2]);}else if(!seenVertex&&Number(p[2])>0)throw Error('当前导入要求 vertex 为首个非空元素');}
   if(p[0]==='property'&&current==='vertex'){if(p[1]==='list'||!types[p[1]])throw Error('不支持该顶点属性类型');props.push({name:p[2],type:p[1],offset:stride});stride+=types[p[1]][0];}}
  if(!Number.isSafeInteger(count)||count<1||count>50000000)throw Error('顶点数量不在支持范围');for(const n of ['x','y','z'])if(!props.some(p=>p.name===n))throw Error('PLY 缺少 '+n);
  const ids=Uint32Array.from({length:Math.min(count,budget)},(_,i)=>Math.floor(i*(count-1)/Math.max(1,Math.min(count,budget)-1))),xyz=[],rgb=[],kept=[],scale=unit==='m'?1000:1;
  let read;
  if(format==='ascii'){if(buffer.byteLength>128*1024*1024)throw Error('大 ASCII PLY 请使用后端导入');const lines=new TextDecoder().decode(buffer.slice(offset)).trim().split(/\r?\n/);if(lines.length<count)throw Error('ASCII PLY 顶点数据不完整');read=id=>{const values=lines[id].trim().split(/\s+/).map(Number);return Object.fromEntries(props.map((p,i)=>[p.name,values[i]]));};}
  else{if(!['binary_little_endian','binary_big_endian'].includes(format)||offset+stride*count>buffer.byteLength)throw Error('PLY 编码不支持或数据被截断');const view=new DataView(buffer),little=format==='binary_little_endian';read=id=>Object.fromEntries(props.map(p=>[p.name,view[types[p.type][1]](offset+id*stride+p.offset,little)]));}
  for(const id of ids){const p=read(id),q=[p.x*scale,p.y*scale,p.z*scale];if(!q.every(Number.isFinite))continue;xyz.push(...q);kept.push(id);for(const name of ['red','green','blue']){let c=p[name]??170;const type=props.find(p=>p.name===name)?.type;if((type==='float'||type==='double'||type==='float32'||type==='float64')&&c<=1)c*=255;rgb.push(Math.round(Math.min(255,Math.max(0,c))));}}
  if(!kept.length)throw Error('没有可显示的有限点');return {points:Float32Array.from(xyz),colors:Uint8Array.from(rgb),originalIds:Uint32Array.from(kept),displayPoints:kept.length,originalPoints:count,unit:'mm',selection:'本地临时预览 · 按原行抽样 · 未上传'};
 }
 const api={parse};root.LocalPly=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
