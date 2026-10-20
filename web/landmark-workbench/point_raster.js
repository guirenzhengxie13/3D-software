/* CPU point splats with a depth buffer. No browser or GPU dependencies. */
(function(root){
  'use strict';
  function rasterize(clouds,matrix,width,height,size=2){
    const rgba=new Uint8ClampedArray(width*height*4),depth=new Float32Array(width*height);depth.fill(Infinity);
    for(let i=0;i<rgba.length;i+=4){rgba[i]=12;rgba[i+1]=20;rgba[i+2]=32;rgba[i+3]=255;}
    const half=Math.max(0,Math.min(3,Math.floor(size/2)));
    for(const cloud of clouds){const p=cloud.points,c=cloud.colors,t=cloud.transform;
      for(let i=0;i<p.length;i+=3){let x=p[i],y=p[i+1],z=p[i+2];
        if(t){const a=x,b=y;x=t[0][0]*a+t[0][1]*b+t[0][2]*z+t[0][3];y=t[1][0]*a+t[1][1]*b+t[1][2]*z+t[1][3];z=t[2][0]*a+t[2][1]*b+t[2][2]*z+t[2][3];}
        const w=matrix[3]*x+matrix[7]*y+matrix[11]*z+matrix[15];if(w<=0)continue;
        const nx=(matrix[0]*x+matrix[4]*y+matrix[8]*z+matrix[12])/w,ny=(matrix[1]*x+matrix[5]*y+matrix[9]*z+matrix[13])/w,nz=(matrix[2]*x+matrix[6]*y+matrix[10]*z+matrix[14])/w;
        if(!Number.isFinite(nx+ny+nz)||Math.abs(nx)>1||Math.abs(ny)>1||Math.abs(nz)>1)continue;
        const sx=Math.round((nx+1)*width/2),sy=Math.round((1-ny)*height/2),rgb=cloud.tint||[c[i],c[i+1],c[i+2]];
        for(let dy=-half;dy<=half;dy++)for(let dx=-half;dx<=half;dx++){
          const xx=sx+dx,yy=sy+dy;if(xx<0||xx>=width||yy<0||yy>=height)continue;
          const pixel=yy*width+xx;if(nz>=depth[pixel])continue;depth[pixel]=nz;
          rgba[pixel*4]=rgb[0];rgba[pixel*4+1]=rgb[1];rgba[pixel*4+2]=rgb[2];
        }
      }
    }
    return rgba;
  }
  const api={rasterize};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.PointRaster=api;
})(typeof globalThis!=='undefined'?globalThis:this);
