import unittest
import numpy as np
import open3d as o3d
from reconstruction_probe.tensor_tsdf import TensorTSDFVolume
from reconstruction_probe.tsdf_trace import read_voxels,lattice_edges,edge_evidence,neighborhood_voxels


class TSDFTraceTests(unittest.TestCase):
    def grid(self):
        grid=TensorTSDFVolume(.001,.004,block_count=8).grid
        grid.hashmap().activate(o3d.core.Tensor(np.array([[-1,0,0],[0,0,0],[1,-1,2]],np.int32)))
        grid.attribute('tsdf').numpy().fill(0);grid.attribute('weight').numpy().fill(0)
        return grid

    def test_xyz_lookup_matches_native_flattened_coordinates_at_negative_block_boundaries(self):
        grid=self.grid();coords,flat=grid.voxel_coordinates_and_flattened_indices();xyz=coords.numpy();flat=flat.numpy().ravel()
        query=np.array([[-1,0,0],[0,0,0],[16,-1,32]],np.int64)
        for i,row in enumerate(query):
            hit=int(np.argmin(np.linalg.norm(xyz-row*.001,axis=1)));self.assertLess(np.linalg.norm(xyz[hit]-row*.001),1e-7)
            grid.attribute('tsdf').reshape((-1,)).numpy()[flat[hit]]=(i+1)*.1;grid.attribute('weight').reshape((-1,)).numpy()[flat[hit]]=i+4
        result=read_voxels(grid,np.vstack([query,[1000,1000,1000]]));np.testing.assert_allclose(result['tsdf'][:3],[.1,.2,.3]);np.testing.assert_array_equal(result['weight'],[4,5,6,0]);self.assertFalse(result['allocated'][3]);self.assertTrue(np.isnan(result['tsdf'][3]))

    def test_reference_point_recovers_negative_y_lattice_edge(self):
        edges=lattice_edges([68.,-12.64505672454834,406.3999938964844],.8)
        self.assertEqual(edges,[dict(axis=1,start=[85,-16,508],end=[85,-15,508])]);self.assertEqual(len(neighborhood_voxels([68,-12,406],.8)),64)
        self.assertEqual(lattice_edges([.13,.25,.37],1.),[])
        with self.assertRaises(ValueError):read_voxels(self.grid(),[[1.2,0,0]])

    def test_strict_threshold_and_interpolation_match_actual_cpu_extraction(self):
        grid=self.grid();query=np.array([[-1,0,0],[0,0,0]],np.int64);coords,flat=grid.voxel_coordinates_and_flattened_indices();xyz=coords.numpy();flat=flat.numpy().ravel();hits=[int(np.argmin(np.linalg.norm(xyz-row*.001,axis=1))) for row in query]
        for k,i in enumerate(hits):grid.attribute('tsdf').reshape((-1,)).numpy()[flat[i]]=[.25,-.25][k];grid.attribute('weight').reshape((-1,)).numpy()[flat[i]]=[3,4][k]
        edge=dict(axis=0,start=[-1,0,0],end=[0,0,0]);state=read_voxels(grid,query);self.assertFalse(edge_evidence(edge,state,1.)['point_extractable']);self.assertEqual(len(grid.extract_point_cloud(weight_threshold=3.).point.positions),0)
        grid.attribute('weight').reshape((-1,)).numpy()[flat[hits[0]]]=4;state=read_voxels(grid,query);result=edge_evidence(edge,state,1.,point_mm=[-.5,0,0]);self.assertTrue(result['point_extractable']);self.assertLess(result['distance_to_reference_mm'],1e-6)
        points=grid.extract_point_cloud(weight_threshold=3.).point.positions.numpy()*1000;self.assertEqual(len(points),1);np.testing.assert_allclose(points[0],[-.5,0,0],atol=1e-5)


if __name__=='__main__':unittest.main()
