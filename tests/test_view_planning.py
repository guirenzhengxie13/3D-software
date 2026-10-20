import unittest
import numpy as np

from reconstruction_probe.view_planning import look_at_optical_pose,minimum_view_separation_degrees,target_visible_from_hit
from reconstruction_probe.visibility import project_depth_observations


class OpticalViewProposalTests(unittest.TestCase):
    def test_look_at_targets_optical_center_without_reflection(self):
        for up in [[-1.,0,0],[0,0,1.]]:
            camera=np.array([30.,20.,-70.]);target=camera+[0,0,100.]
            matrix=look_at_optical_pose(camera,target,up)
            self.assertAlmostEqual(np.linalg.det(matrix[:3,:3]),1)
            observed=project_depth_observations([target],matrix,np.full((3,3),100.),dict(width=3,height=3,K=[[10,0,1],[0,10,1],[0,0,1]]),[1,1,1])
            np.testing.assert_array_equal(observed.pixel_indices,[4]);np.testing.assert_allclose(observed.signed_delta_mm,0,atol=1e-10)

    def test_nearest_observed_direction_controls_novelty(self):
        angles=minimum_view_separation_degrees([[0,0,1],[1,0,0],[0,0,-1]],[[0,0,10]])
        np.testing.assert_allclose(angles,[0,90,180])

    def test_ray_hitting_a_nearer_surface_is_not_target_visibility(self):
        result=target_visible_from_hit([90,100.3,np.inf],[100,100,100],.6)
        np.testing.assert_array_equal(result,[False,True,False])


if __name__=="__main__":unittest.main()
