import unittest
import numpy as np
from scipy.spatial.transform import Rotation

from reconstruction_probe.turntable import predict_fixed_axis_poses


class FixedAxisPredictionTests(unittest.TestCase):
    def test_known_axis_motion_and_unobservable_axial_point_shift(self):
        axis=np.array([1.,0,0]);center=np.array([0.,-40,420.]);anchor=np.eye(4);anchor[:3,3]=[5,-8,20]
        relative=np.repeat(np.eye(4)[None],7,axis=0);rotation=Rotation.from_rotvec(np.linspace(0,5,7)[:,None]*axis).as_matrix()
        relative[:,:3,:3]=rotation;relative[:,:3,3]=np.einsum('nij,j->ni',np.eye(3)-rotation,center);poses=relative@anchor
        first=predict_fixed_axis_poses(poses,axis,center,anchor);second=predict_fixed_axis_poses(poses,axis,center+axis*200,anchor)
        np.testing.assert_allclose(first,poses,atol=1e-10);np.testing.assert_allclose(first,second,atol=1e-10)

    def test_improper_pose_cannot_be_used_to_predict_an_axis_trajectory(self):
        bad=np.eye(4);bad[0,0]=-1
        with self.assertRaises(ValueError):predict_fixed_axis_poses([bad],[1,0,0],[0,0,400],np.eye(4))


if __name__=='__main__':unittest.main()
