import unittest
import numpy as np

from reconstruction_probe.visibility import depth_observation_deltas


class DepthEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.calibration={"width":3,"height":3,"K":[[10,0,1],[0,10,1],[0,0,1]]}

    def test_known_plane_distinguishes_support_conflict_and_occlusion(self):
        points=np.array([[0,0,99],[0,0,80],[0,0,120],[0,0,-5],[100,0,100]])
        ids,delta=depth_observation_deltas(points,np.eye(4),np.full((3,3),100.),self.calibration,[1,1,1])
        np.testing.assert_array_equal(ids,[0,1,2])
        np.testing.assert_array_equal(delta,[1,20,-20])

    def test_world_pose_is_inverted_before_projecting(self):
        pose=np.array([[0,-1,0,20],[1,0,0,30],[0,0,1,40],[0,0,0,1]],float)
        optical=np.array([[0,0,100.]])
        world=optical@pose[:3,:3].T+pose[:3,3]
        ids,delta=depth_observation_deltas(world,pose,np.full((3,3),100.),self.calibration,[1,1,1])
        np.testing.assert_array_equal(ids,[0]);np.testing.assert_allclose(delta,0)

    def test_scaled_calibration_and_missing_depth_provide_correct_evidence(self):
        calibration={"width":6,"height":6,"K":[[20,0,2],[0,20,2],[0,0,1]]}
        depth=np.zeros((3,3));depth[1,2]=105
        ids,delta=depth_observation_deltas([[10,0,100],[0,0,100]],np.eye(4),depth,calibration,[1,1,1])
        np.testing.assert_array_equal(ids,[0]);np.testing.assert_array_equal(delta,[5])

    def test_legacy_axis_conversion_also_applies_to_visibility(self):
        ids,delta=depth_observation_deltas([[0,0,-100]],np.eye(4),np.full((3,3),100.),self.calibration,[1,-1,-1])
        np.testing.assert_array_equal(ids,[0]);np.testing.assert_array_equal(delta,[0])

    def test_common_rigid_rebase_preserves_signed_evidence_for_both_axis_conventions(self):
        # A target camera and candidate points must enter the same reference.
        # Noncommuting rotations catch an inverse or composition-order mistake.
        camera=np.array([[0,-1,0,20],[1,0,0,30],[0,0,1,40],[0,0,0,1]],float)
        a,b=np.deg2rad([70.,31.])
        rx=np.array([[1,0,0],[0,np.cos(a),-np.sin(a)],[0,np.sin(a),np.cos(a)]])
        ry=np.array([[np.cos(b),0,np.sin(b)],[0,1,0],[-np.sin(b),0,np.cos(b)]])
        rebase=np.eye(4);rebase[:3,:3]=rx@ry;rebase[:3,3]=[230,-410,780]
        optical=np.array([[0,0,100.],[8,0,100.],[-8,0,100.],[0,0,110.]])
        depth=np.full((3,3),100.);depth[1]=[99.,104.,97.]
        for signs in ([1,1,1],[1,-1,-1]):
            native=(optical*signs)@camera[:3,:3].T+camera[:3,3]
            ids,delta=depth_observation_deltas(native,camera,depth,self.calibration,signs)
            moved=native@rebase[:3,:3].T+rebase[:3,3]
            ids_new,delta_new=depth_observation_deltas(moved,rebase@camera,depth,self.calibration,signs)
            np.testing.assert_array_equal(ids_new,ids)
            np.testing.assert_allclose(delta_new,delta,rtol=0,atol=1e-10)


if __name__ == "__main__":unittest.main()
