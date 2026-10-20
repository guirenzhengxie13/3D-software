"""Trace a sampled surface point to supporting saved depth/color pixels."""

import argparse
import html
import json
from pathlib import Path

import numpy as np
from PIL import Image,ImageDraw

from build_attribute_study_report import font
from reconstruct_scans import clean_depth_edges,optical_to_pose_axes,write_json
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.visibility import project_depth_observations
from reconstruction_probe.view_coverage import support_view_indices


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--coverage',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    selection=parser.add_mutually_exclusive_group(required=True);selection.add_argument('--sample-index',type=int);selection.add_argument('--proposal-region',type=int)
    parser.add_argument('--proposal-plan',type=Path)
    args=parser.parse_args();root=args.coverage.resolve();out=args.out.resolve()
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);summary=read(root/'summary.json');decoded=Path(summary['decoded_path']);index=read(decoded/'index.json')
    sample=args.sample_index
    if args.proposal_region is not None:
        if args.proposal_plan is None:parser.error('--proposal-region requires --proposal-plan')
        plan=read(args.proposal_plan)
        if plan.get('input_sha256',{}).get(str(root/'coverage-data.npz'))!=file_sha256(root/'coverage-data.npz'):raise ValueError('Proposal plan uses different coverage data')
        regions=[r for r in plan['recommendations'] if r['region_rank']==args.proposal_region]
        if len(regions)!=1:raise ValueError('Proposal region not found')
        sample=regions[0]['representative_sample_index']
    with np.load(root/'coverage-data.npz',allow_pickle=False) as data:
        if not 0<=sample<len(data['xyz_scan_mm']):raise ValueError('Sample index outside coverage data')
        xyz=data['xyz_scan_mm'][sample].copy();point_id=int(data['source_point_indices'][sample]);frame_ids=data['frame_ids'].copy();centers=data['camera_centers_mm'].copy()
        supporting=support_view_indices(data['support_view_bits'][sample],len(frame_ids));best=int(data['best_view_index'][sample])
        separation=float(data['first_support_max_separation_deg'][sample]);category=int(data['categories'][sample]);best_pixel=int(data['best_view_pixel_index'][sample])
    if not len(supporting):raise ValueError('Selected point has no 2mm supporting view; choose another or inspect raw observations')
    rays=centers-xyz;rays/=np.linalg.norm(rays,axis=1)[:,None]
    selected=[]
    for name,ordinal in [('最佳入射角支持帧',best),('首个支持帧',int(supporting[0])),('与首支持方向最远的支持帧',int(supporting[np.argmin(rays[supporting]@rays[supporting[0]])]))]:
        if ordinal>=0 and all(ordinal!=i for _,i in selected):selected.append((name,ordinal))
    poses=np.load(Path(summary['pose_overrides_path']),allow_pickle=False)
    def frame_data(ordinal):
        rid=int(frame_ids[ordinal]);folder=decoded/f'frame_{rid:010d}'
        with np.load(folder/'frame.npz',allow_pickle=False) as saved:
            original=saved['depth_mm'];rgba=saved['rgba'] if 'rgba' in saved else None
            if rgba is not None and int(saved['color_layout_version'])!=2:raise ValueError('Verified color layout required')
        depth,_=clean_depth_edges(original,3.)
        observed=project_depth_observations(xyz[None,:],poses[f'pose_{rid}'],depth,index['intrinsics']['Pl'],optical_to_pose_axes(index))
        if not len(observed.point_indices):return None
        pixel=int(observed.pixel_indices[0]);delta=float(observed.signed_delta_mm[0]);h,w=depth.shape;v,u=divmod(pixel,w)
        rgb=np.zeros((h,w,3),np.uint8)
        if rgba is not None:rgb[original>0]=rgba[:,:3]
        else:
            good=original>0;values=original[good];gray=np.rint(60+180*(values-values.min())/max(float(np.ptp(values)),1e-6)).astype(np.uint8);rgb[good]=gray[:,None]
        return dict(frame_id=rid,frame_ordinal=ordinal,pixel_index=pixel,u=u,v=v,delta_mm=delta,observation='support' if abs(delta)<=2 else 'free_space_conflict' if delta>2 else 'occluded',rgb=rgb)
    already={ordinal for _,ordinal in selected}
    opposite=np.argsort(rays@rays[supporting[0]])
    for ordinal in opposite[:20]:
        if int(ordinal) in already:continue
        frame=frame_data(int(ordinal))
        if frame is not None and frame['observation']!='support':selected.append(('不同方向的观测示例',int(ordinal)));break
    pictures=[];records=[]
    for name,ordinal in selected:
        row=frame_data(ordinal)
        if row is None:continue
        if ordinal==best and row['pixel_index']!=best_pixel:raise ValueError('Best-view pixel provenance changed')
        rgb=row.pop('rgb');image=Image.fromarray(rgb);marked=image.copy();draw=ImageDraw.Draw(marked);u,v=row['u'],row['v']
        draw.ellipse((u-8,v-8,u+8,v+8),outline='#ff6380',width=2);draw.line((u-13,v,u+13,v),fill='#ffffff',width=1);draw.line((u,v-13,u,v+13),fill='#ffffff',width=1)
        filename=f"frame-{row['frame_id']}-aligned-color.png";marked.save(out/filename)
        crop=image.crop((u-40,v-40,u+41,v+41)).resize((162,162),Image.Resampling.NEAREST);cd=ImageDraw.Draw(crop);cd.ellipse((75,75,87,87),outline='#ff6380',width=2)
        crop_name=f"frame-{row['frame_id']}-crop.png";crop.save(out/crop_name)
        card=Image.new('RGB',(420,590),(24,33,47));d=ImageDraw.Draw(card);d.text((12,10),name,font=font(17),fill='#edf3fa');d.text((12,40),f"ID {row['frame_id']} · {row['observation']} · ΔZ {row['delta_mm']:.3f} mm",font=font(14),fill='#b1c5db')
        card.paste(marked.resize((400,300),Image.Resampling.NEAREST),(10,75));card.paste(crop,(12,400));d.text((190,415),f"像素 ({u}, {v})",font=font(16),fill='#edf3fa');d.text((190,445),'左下：局部放大',font=font(15),fill='#b1c5db');pictures.append(card)
        row.update(label=name,color_image=filename,crop_image=crop_name);records.append(row)
    poses.close()
    sheet=Image.new('RGB',(420*len(pictures),625),(24,33,47))
    for i,picture in enumerate(pictures):sheet.paste(picture,(i*420,0))
    ImageDraw.Draw(sheet).text((12,600),'颜色已对齐到深度像素，无深度处为黑色；标记为该三维点投影，不是人工新增深度。',font=font(15),fill='#b1c5db');sheet.save(out/'evidence.png')
    report=dict(sample_index=sample,original_surface_point_id=point_id,xyz_scan_mm=xyz.tolist(),coverage_category=category,
        support_frame_ids=frame_ids[supporting].tolist(),support_views=len(supporting),first_support_max_separation_deg=separation,
        displayed_frames=records,input_sha256={str(p):file_sha256(p) for p in [root/'summary.json',root/'coverage-data.npz',Path(summary['pose_overrides_path'])]},
        limitations=['A supporting pixel means signed depth agrees within 2 mm; it does not establish physical accuracy.',
          'Colors are decoded depth-aligned pixels, not the full original JPEG view. Missing-depth areas are black.',
          'The surface and observing depths share source data; these are provenance/internal checks, not independent validation.'])
    if args.proposal_plan is not None:report['input_sha256'][str(args.proposal_plan.resolve())]=file_sha256(args.proposal_plan)
    write_json(out/'summary.json',report)
    (out/'README.md').write_text(f"# 表面点回查\n\n原 PLY 点编号 {point_id}；覆盖抽样编号 {sample}。{len(supporting)} 个保存深度视图在 2 mm 内支持该点，与首支持视角的最大夹角为 {separation:.2f}°。\n\n![支持帧与像素](evidence.png)\n\n[逐帧 ID、像素和深度差](summary.json)。三维点会投影到具体深度像素；相同像素的对齐颜色用于显示，黑色区域没有深度。该点是否属于正确物体表面仍须结合整体几何判断。\n",encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['sample_index','original_surface_point_id','support_views','first_support_max_separation_deg','displayed_frames']}),flush=True)


if __name__=='__main__':main()
