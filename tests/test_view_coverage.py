import unittest
import numpy as np

from reconstruction_probe.view_coverage import ViewDirectionAccumulator,support_view_indices
from reconstruction_probe.visibility import project_depth_observations


class SavedViewCoverageTests(unittest.TestCase):
    def test_repeating_one_view_does_not_create_angular_diversity(self):
        accumulator=ViewDirectionAccumulator(2)
        for _ in range(25):accumulator.add(np.array([0]),[[0,0,500]])
        metrics=accumulator.metrics()
        self.assertEqual(accumulator.count[0],25)
        self.assertAlmostEqual(metrics['first_support_max_separation_deg'][0],0)
        self.assertTrue(np.isnan(metrics['first_support_max_separation_deg'][1]))

    def test_two_views_have_known_separation_and_rebase_invariance(self):
        rays=np.array([[.5,0,np.sqrt(.75)],[-.5,0,np.sqrt(.75)]])
        rotation=np.array([[0,-1,0],[0,0,-1],[1,0,0]],float)
        outputs=[]
        for points in [rays,rays@rotation.T]:
            accumulator=ViewDirectionAccumulator(1)
            for ray in points:accumulator.add(np.array([0]),[ray])
            outputs.append(accumulator.metrics())
        self.assertAlmostEqual(outputs[0]['first_support_max_separation_deg'][0],60)
        self.assertAlmostEqual(outputs[0]['resultant_equivalent_angle_deg'][0],30)
        np.testing.assert_allclose(outputs[0]['first_support_max_separation_deg'],outputs[1]['first_support_max_separation_deg'])

    def test_projection_retains_exact_depth_pixel_identity(self):
        calibration=dict(width=3,height=3,K=[[10,0,1],[0,10,1],[0,0,1]])
        depth=np.zeros((3,3));depth[1,2]=105
        observed=project_depth_observations([[10,0,100],[0,0,100]],np.eye(4),depth,calibration,[1,1,1])
        np.testing.assert_array_equal(observed.point_indices,[0]);np.testing.assert_array_equal(observed.pixel_indices,[5]);np.testing.assert_array_equal(observed.signed_delta_mm,[5])

    def test_support_mask_preserves_ids_across_byte_boundaries(self):
        np.testing.assert_array_equal(support_view_indices(np.array([0b10000001,0b00000001],np.uint8),9),[0,7,8])
        with self.assertRaises(ValueError):support_view_indices(np.array([0,0b10000001],np.uint8),9)


if __name__=="__main__":unittest.main()
