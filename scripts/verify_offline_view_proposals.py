"""Audit proposal frames/rays and run a known occlusion/metric-scale control."""

import argparse
import json
from pathlib import Path

import numpy as np
import open3d as o3d

from reconstruction_probe.offline import file_sha256
from reconstruction_probe.poses import _rigid_matrix
from reconstruction_probe.view_coverage import support_view_indices
from reconstruction_probe.view_planning import minimum_view_separation_degrees,target_visible_from_hit


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--coverage',type=Path,required=True);parser.add_argument('--proposals',type=Path,required=True)
    args=parser.parse_args();coverage=args.coverage.resolve();proposals=args.proposals.resolve();report=read(proposals/'summary.json');meta=read(coverage/'summary.json')
    for name,digest in report['input_sha256'].items():
        if file_sha256(Path(name))!=digest:raise ValueError('Proposal input changed: '+name)
    box=o3d.geometry.TriangleMesh.create_box(10,10,10);control=o3d.t.geometry.RaycastingScene();control.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(box))
    hits=control.cast_rays(o3d.core.Tensor(np.array([[5,5,100,0,0,-1],[5,5,100,0,0,-2],[20,20,100,0,0,-1]],np.float32)))['t_hit'].numpy()
    np.testing.assert_allclose(hits[:2],[90,45],atol=1e-4);assert np.isinf(hits[2])
    np.testing.assert_array_equal(target_visible_from_hit([hits[0],hits[0],hits[2]],[90,100,100],1.2),[True,False,False])
    with np.load(coverage/'coverage-data.npz',allow_pickle=False) as z:data={k:z[k].copy() for k in z.files}
    weak=np.flatnonzero(np.isin(data['categories'],[2,3]));cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(data['xyz_scan_mm'][weak])
    labels=np.array(cloud.cluster_dbscan(eps=4.,min_points=25,print_progress=False))
    mesh=o3d.io.read_triangle_mesh(str(Path(meta['geometry_path']).parent/'tsdf_mesh_mm.ply'));scene=o3d.t.geometry.RaycastingScene();scene.add_triangles(o3d.t.geometry.TriangleMesh.from_legacy(mesh))
    calibration=read(Path(meta['decoded_path'])/'index.json')['intrinsics']['Pl'];K=np.array(calibration['K']);checked=0
    for row in report['recommendations']:
        if row['status']!='proposal_requires_human_review':continue
        pose=np.array(row['suggested_camera_to_scan_mm'],dtype='<f8');_rigid_matrix(pose.tobytes(),0,1e-5)
        target=np.array(row['target_scan_mm']);camera=pose[:3,3];distance=np.linalg.norm(target-camera)
        np.testing.assert_allclose((target-camera)@pose[:3,:3],[0,0,row['working_distance_mm']],atol=1e-9)
        supporting=support_view_indices(data['support_view_bits'][row['representative_sample_index']],len(data['frame_ids']))
        novelty=minimum_view_separation_degrees((camera-target)[None,:],data['camera_centers_mm'][supporting]-target)[0]
        assert abs(novelty-row['minimum_angle_from_existing_supported_views_deg'])<1e-8 and novelty>=15
        region=weak[labels==row['cluster_id']];sampled=data['xyz_scan_mm'][region][np.linspace(0,len(region)-1,min(64,len(region)),dtype=int)]
        vector=sampled-camera;ranges=np.linalg.norm(vector,axis=1);directions=vector/ranges[:,None]
        rays=np.column_stack((np.tile(camera,(len(sampled),1)),directions)).astype(np.float32);hit=scene.cast_rays(o3d.core.Tensor(rays))['t_hit'].numpy()
        optical=vector@pose[:3,:3];u=optical[:,0]/optical[:,2]*K[0,0]+K[0,2];v=optical[:,1]/optical[:,2]*K[1,1]+K[1,2]
        visible=target_visible_from_hit(hit,ranges,1.2)&(optical[:,2]>0)&(u>=0)&(u<calibration['width'])&(v>=0)&(v<calibration['height'])
        fraction=float(visible.mean());assert abs(fraction-row['region_visible_fraction_on_current_mesh'])<1e-12 and fraction>=.8
        assert abs(distance-row['working_distance_mm'])<1e-9;checked+=1
    result=dict(known_box_metric_ray_control_passed=True,nearer_surface_rejected=True,proposed_optical_poses_checked=checked,
        novelty_and_visibility_recomputed=True,actual_physical_visibility_verified=False)
    (proposals/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result))


if __name__=='__main__':main()
