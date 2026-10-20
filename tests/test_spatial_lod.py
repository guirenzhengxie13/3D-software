import unittest

import numpy as np

from reconstruction_probe.spatial_lod import budgeted_spatial_preview,voxel_representative_ids,RepresentativeCapacityExceeded


def records(points):
    result=np.empty(len(points),dtype=[('x','<f8'),('y','<f8'),('z','<f8')])
    for i,name in enumerate(['x','y','z']):result[name]=np.asarray(points)[:,i]
    return result


class SpatialPreviewTests(unittest.TestCase):
    def test_original_vertex_choice_is_identical_across_chunk_boundaries(self):
        source=records([[.1,.1,.1],[.49,.49,.49],[.51,.51,.51],[1.4,.5,.5],[1.6,.5,.5],[np.nan,0,0]])
        expected=voxel_representative_ids(source,1.,[0,0,0],100,chunk_size=100)
        for size in [1,2,3]:np.testing.assert_array_equal(voxel_representative_ids(source,1.,[0,0,0],100,chunk_size=size),expected)
        np.testing.assert_array_equal(expected,[1,3])

    def test_capacity_guard_stops_an_overfine_preview(self):
        source=records(np.column_stack([np.arange(100.),np.zeros((100,2))]))
        with self.assertRaises(RepresentativeCapacityExceeded):voxel_representative_ids(source,.1,[0,0,0],10,chunk_size=20)

    def test_budget_and_voxel_coverage_bound_hold_for_a_plane_and_rare_detached_points(self):
        rng=np.random.default_rng(14);points=np.c_[rng.uniform(0,10,(5000,2)),np.zeros(5000)];points=np.vstack([points,[30,0,0],[30,1,0]])
        result=budgeted_spatial_preview(records(points),budget=100,chunk_size=177)
        self.assertLessEqual(len(result['ids']),100);self.assertEqual(len(np.unique(result['ids'])),len(result['ids']))
        self.assertTrue(np.any(result['ids']>=5000))
        representatives=points[result['ids']];distance=np.linalg.norm(points[:,None,:]-representatives[None,:,:],axis=2).min(1)
        self.assertLessEqual(distance.max(),result['coverage_distance_upper_bound_mm']+1e-9)

    def test_small_or_degenerate_input_preserves_valid_original_identity(self):
        source=records([[1,2,3],[np.nan,1,1],[4,5,6]])
        np.testing.assert_array_equal(budgeted_spatial_preview(source,10)['ids'],[0,2])
        duplicate=records(np.tile([1,2,3],(100,1)))
        self.assertEqual(budgeted_spatial_preview(duplicate,1)['ids'].tolist(),[0])
        with self.assertRaises(ValueError):budgeted_spatial_preview(source,True)


if __name__=='__main__':unittest.main()
