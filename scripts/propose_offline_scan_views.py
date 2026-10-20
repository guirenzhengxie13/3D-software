"""Suggest object-relative inspection views for observed weak-coverage regions.

These are heuristic proposals from an estimated, incomplete mesh. They are
not device commands, absolute room poses, or an optimal information planner.
"""

import os
os.environ.setdefault('OMP_NUM_THREADS','4')

import argparse
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image,ImageDraw
import numpy as np
import open3d as o3d

from reconstruct_scans import write_json
from build_attribute_study_report import render,font
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.view_coverage import support_view_indices
from reconstruction_probe.view_planning import fibonacci_directions,look_at_optical_pose,minimum_view_separation_degrees,target_visible_from_hit


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def line_points(first,second,count=35):return np.linspace(first,second,count)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--coverage',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--max-regions',type=int,default=6)
    args=parser.parse_args();coverage=args.coverage.resolve();out=args.out.resolve()
    if not 1<=args.max_regions<=12:parser.error('Use 1..12 regions')
    if out.exists() and any(out.iterdir()):parser.error('Use a new/empty output directory')
    out.mkdir(parents=True,exist_ok=True);summary=read(coverage/'summary.json');decoded=Path(summary['decoded_path']);index=read(decoded/'index.json')
    with np.load(coverage/'coverage-data.npz',allow_pickle=False) as saved:data={key:saved[key].copy() for key in saved.files}
    xyz=data['xyz_scan_mm'];weak=np.flatnonzero(np.isin(data['categories'],[2,3]))
    cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(xyz[weak]);clusters=np.array(cloud.cluster_dbscan(eps=4.,min_points=25,print_progress=False))
    ids=sorted(set(clusters.tolist())-{-1},key=lambda group:-(clusters==group).sum())[:args.max_regions]
    mesh_path=Path(summary['geometry_path']).parent/'tsdf_mesh_mm.ply';mesh=o3d.io.read_triangle_mesh(str(mesh_path))
    scene=o3d.t.geometry.RaycastingScene();scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    calibration=index['intrinsics']['Pl'];K=np.array(calibration['K']);directions=fibonacci_directions(192)
    rows=[];guides=[];guide_colors=[];tolerance_mm=1.2
    palette_values=np.array([[84,182,242],[240,157,77],[116,205,143],[205,129,228],[237,116,135],[224,205,98],[91,210,204],[176,181,244],[196,155,117],[178,191,204]],float)/255
    def palette(i):return palette_values[int(i)%len(palette_values)]
    for rank,cluster in enumerate(ids):
        selected=weak[clusters==cluster];points=xyz[selected];center=points.mean(0);representative=int(selected[np.argmin(np.linalg.norm(points-center,axis=1))]);target=xyz[representative]
        mean_normal=data['normal_toward_first_support'][selected].mean(0);coherence=float(np.linalg.norm(mean_normal))
        supporting=support_view_indices(data['support_view_bits'][representative],len(data['frame_ids']))
        row=dict(region_rank=rank+1,cluster_id=int(cluster),sample_points=len(selected),representative_sample_index=representative,
            original_surface_point_id=int(data['source_point_indices'][representative]),target_scan_mm=target.tolist(),normal_coherence=coherence,
            existing_support_views=len(supporting),first_support_max_separation_deg=float(data['first_support_max_separation_deg'][representative]) if len(supporting) else None)
        if coherence<.7 or len(supporting)<3:
            row.update(status='needs_region_review',reason='Insufficient representative observations or coherent local normal');rows.append(row);continue
        normal=mean_normal/coherence;existing=data['camera_centers_mm'][supporting]-target
        novelty=minimum_view_separation_degrees(directions,existing);incidence=directions@normal
        allowed=(novelty>=15)&(incidence>=.35)
        chosen=np.flatnonzero(allowed)
        if not len(chosen):row.update(status='no_proposal',reason='No sampled direction clears the fixed novelty/incidence gates');rows.append(row);continue
        distance=float(np.median(np.linalg.norm(existing,axis=1)));origins=target+directions[chosen]*distance
        sampled=points[np.linspace(0,len(points)-1,min(64,len(points)),dtype=int)];m=len(sampled)
        ray_origins=np.repeat(origins,m,axis=0);ray_targets=np.tile(sampled,(len(origins),1));ray_vector=ray_targets-ray_origins
        ray_lengths=np.linalg.norm(ray_vector,axis=1);unit=ray_vector/ray_lengths[:,None]
        rays=o3d.core.Tensor(np.column_stack((ray_origins,unit)).astype(np.float32));hits=scene.cast_rays(rays)['t_hit'].numpy()
        visible=target_visible_from_hit(hits,ray_lengths,tolerance_mm).reshape(len(origins),m)
        poses=[]
        for i,origin in enumerate(origins):
            pose=look_at_optical_pose(origin,target);poses.append(pose)
            optical=(sampled-origin)@pose[:3,:3];z=optical[:,2]
            u=optical[:,0]/z*K[0,0]+K[0,2];v=optical[:,1]/z*K[1,1]+K[1,2]
            visible[i]&=(z>0)&(u>=0)&(u<calibration['width'])&(v>=0)&(v<calibration['height'])
        fractions=visible.mean(1);passing=fractions>=.8
        row.update(sampled_candidate_directions=len(chosen),region_probe_points=m,visible_candidates_passing_80pct=int(passing.sum()))
        if not passing.any():row.update(status='no_proposal',reason='Current mesh occludes too much of the region from all eligible directions');rows.append(row);continue
        scores=.5*fractions+.3*incidence[chosen]+.2*np.minimum(novelty[chosen]/90,1);scores[~passing]=-np.inf;best=int(np.argmax(scores));which=chosen[best];pose=poses[best];camera=origins[best]
        row.update(status='proposal_requires_human_review',suggested_camera_to_scan_mm=pose.tolist(),suggested_camera_center_mm=camera.tolist(),
            working_distance_mm=distance,view_direction_from_target=directions[which].tolist(),minimum_angle_from_existing_supported_views_deg=float(novelty[which]),
            region_visible_fraction_on_current_mesh=float(fractions[best]),heuristic_score=float(scores[best]),representative_normal_scan=normal.tolist())
        rows.append(row)
        color=np.array(palette(rank%10)[:3]);pieces=[line_points(target,camera,150)]
        # A small optical frustum drawn at its actual proposed location.
        corners=[]
        for u,v in [(0,0),(calibration['width'],0),(calibration['width'],calibration['height']),(0,calibration['height'])]:
            local=np.array([(u-K[0,2])*25/K[0,0],(v-K[1,2])*25/K[1,1],25.]);corners.append(local@pose[:3,:3].T+camera)
        for corner in corners:pieces.append(line_points(camera,corner))
        for i in range(4):pieces.append(line_points(corners[i],corners[(i+1)%4]))
        merged=np.concatenate(pieces);guides.append(merged);guide_colors.append(np.tile(color,(len(merged),1)))
    proposals=[row for row in rows if row['status']=='proposal_requires_human_review']
    report=dict(method='Cluster currently observed narrow/low-support points; rank novel camera directions with incidence and current-mesh ray visibility',
        coordinate_frame=summary['coordinate_frame'],recommendations=rows,proposals=len(proposals),
        rules=dict(weak_categories=[2,3],conflict_category_excluded=4,cluster_eps_mm=4.,cluster_min_points=25,normal_coherence_min=.7,
            sphere_samples=192,minimum_novel_angle_deg=15.,minimum_normal_dot=.35,minimum_region_visible_fraction=.8,ray_target_tolerance_mm=tolerance_mm),
        input_sha256={str(p):file_sha256(p) for p in [coverage/'summary.json',coverage/'coverage-data.npz',mesh_path,decoded/'index.json']},
        method_source='https://www.open3d.org/docs/latest/tutorial/geometry/ray_casting.html',
        limitations=['Only observed weak regions are proposed; completely unseen object shape is not recovered or assumed.',
          'A line of sight clear in an incomplete estimated mesh can still be wrong in the physical scene.',
          'Proposed poses are relative to the reconstructed object, not room coordinates or executable scanner/robot motion commands.',
          'Novelty refers to the representative point, and the visibility fraction uses at most 64 sampled region points.',
          'The heuristic score is not expected information gain, optimal planning, or a probability of successful scanning.',
          'Repeated-conflict regions are excluded from rescan proposals; alignment and interpretation should be reviewed first.',
          'The region must be checked against the real object before treating it as a useful rescan target.'])
    write_json(out/'summary.json',report)
    if guides:
        guide=o3d.geometry.PointCloud();guide.points=o3d.utility.Vector3dVector(np.concatenate(guides));guide.colors=o3d.utility.Vector3dVector(np.concatenate(guide_colors));guide_path=out/'auxiliary-camera-guides-mm.ply';o3d.io.write_point_cloud(str(guide_path),guide)
        command=[sys.executable,'scripts/build_reconstruction_review.py','--unit','mm','--up-axis','x','--invert-up','--allow-overlay','--max-points','40000','--out',str(out/'review.html'),'--notes','相机位置与视线是辅助建议几何，不属于扫描点云。坐标相对物体，不是房间位置或设备指令。默认先看模型，叠加后可查看建议视点；初步射线可见性基于不完整估计模型。','--cloud','物体表面='+str(summary['geometry_path']),'--cloud','建议相机与视线（辅助几何）='+str(guide_path)]
        subprocess.run(command,check=True,stdout=subprocess.DEVNULL)
    physical=o3d.io.read_point_cloud(summary['geometry_path'])
    figure=Image.new('RGB',(1600,800),(24,33,47));draw=ImageDraw.Draw(figure)
    extra=[np.array(row['target_scan_mm'])+np.array(row['view_direction_from_target'])*35 for row in proposals]
    combined=np.concatenate([xyz,np.array(extra)]) if extra else xyz
    bounds=(combined.min(0),combined.max(0));lower,upper=bounds;center=(lower+upper)/2
    corners=np.array([[x,y,z] for x in (lower[0],upper[0]) for y in (lower[1],upper[1]) for z in (lower[2],upper[2])])
    for view,yaw in enumerate([1.2,-1.1]):
        pitch=.15;width,height=790,630;offset=np.array([view*800+5,65])
        figure.paste(render(physical,(width,height),yaw=yaw,pitch=pitch,bounds=bounds),tuple(offset))
        direction=np.array([-np.sin(pitch),np.cos(yaw)*np.cos(pitch),np.sin(yaw)*np.cos(pitch)])
        right=np.cross(direction,[-1.,0,0]);right/=np.linalg.norm(right);up=np.cross(right,direction)
        corner_uv=np.column_stack(((corners-center)@right,(corners-center)@up))
        scale=.84/max(np.ptp(corner_uv[:,0])/width,np.ptp(corner_uv[:,1])/height,1e-6)
        def screen(point):
            q=point-center
            return np.array([q@right*scale+width/2,-q@up*scale+height/2])+offset
        draw.text((view*800+15,12),f'建议观察方向 · 视角 {view+1}',font=font(23),fill='#edf3fa')
        for row in proposals:
            point=np.array(row['target_scan_mm']);endpoint=point+np.array(row['view_direction_from_target'])*35
            start,end=screen(point),screen(endpoint);color=tuple(np.rint(palette(row['region_rank']-1)*255).astype(int))
            draw.line([tuple(start),tuple(end)],fill=color,width=3);draw.ellipse((start[0]-4,start[1]-4,start[0]+4,start[1]+4),fill=color)
            delta=end-start;length=np.linalg.norm(delta)
            if length>3:
                unit=delta/length;side=np.array([-unit[1],unit[0]]);base=end-unit*12
                draw.polygon([tuple(end),tuple(base+side*5),tuple(base-side*5)],fill=color)
            draw.text(tuple(end+np.array([7,-15])),f"R{row['region_rank']}",font=font(20),fill=color)
    draw.text((15,725),'箭头从区域指向建议相机方向，长度仅为显示；实际相机距离与位姿见表。',font=font(20),fill='#c5d8ec')
    draw.text((15,763),'建议在物体参考系中；当前网格的可见性检查仍需结合实物判断。',font=font(18),fill='#a7bfd6')
    figure.save(out/'directions.png')
    lines=['# 离线补扫观察方向建议','','这一步不需要实时 SDK：先用离线包找出“已经有表面、但支持视角集中”的区域，再给出相对物体的观察方向候选。它不推断完全没扫到的形状，也不自动安排真实设备运动。','','![方向建议](directions.png)','','图中箭头从区域指向建议相机方向，长度只为显示；实际建议距离见表。','','| 区域 | 抽样点 | 代表点支持帧 | 已有首视角夹角 | 建议方向距已有最近角 | 当前网格可见比例 | 建议距离 mm |','| --- | --- | --- | --- | --- | --- | --- |']
    for row in proposals:lines.append(f"| R{row['region_rank']} | {row['sample_points']:,} | {row['existing_support_views']} | {row['first_support_max_separation_deg']:.1f}° | {row['minimum_angle_from_existing_supported_views_deg']:.1f}° | {row['region_visible_fraction_on_current_mesh']:.1%} | {row['working_distance_mm']:.1f} |")
    lines+=['','候选由固定启发式选出：观察方向新颖、入射角合适，并且当前网格的射线检查显示至少 80% 抽样区域可见。射线实现参考 [Open3D 官方文档](https://www.open3d.org/docs/latest/tutorial/geometry/ray_casting.html)。这不等于真实场景已验证可见，也不是最优信息增益规划。','','有重复深度冲突的区域不自动列为补扫目标，应先检查配准与表面解释。没有合格建议的区域也保留了拒绝原因。所有相机位姿均在物体参考系中，转台情况下不能直接当作房间中的相机轨迹。','','[区域、建议矩阵与拒绝原因](summary.json)'+(' · [模型与建议相机三维对照](review.html)' if guides else '')]
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(regions=len(rows),proposals=len(proposals),recommendations=rows)),flush=True)


if __name__=='__main__':main()
