import unittest
import numpy as np
import open3d as o3d

from reconstruction_probe.tensor_tsdf import TensorTSDFVolume


class TensorTSDFTests(unittest.TestCase):
    def test_extraction_weight_gate_does_not_invent_unobserved_support(self):
        rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.full((30,40,3),100,np.uint8)),
            o3d.geometry.Image(np.full((30,40),200,np.uint16)),depth_scale=1000,depth_trunc=1,convert_rgb_to_intensity=False)
        volume=TensorTSDFVolume(.005,.02,block_count=100)
        volume.integrate(rgbd,o3d.camera.PinholeCameraIntrinsic(40,30,60,60,20,15),np.eye(4))
        self.assertGreater(len(volume.extract_point_cloud().points),100)
        volume.weight_threshold=2.
        self.assertEqual(len(volume.extract_point_cloud().points),0)

    def test_known_metric_plane_and_color_are_preserved(self):
        rgbd=o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.full((30,40,3),[40,100,180],np.uint8)),
            o3d.geometry.Image(np.full((30,40),200,np.uint16)),depth_scale=1000,depth_trunc=1,convert_rgb_to_intensity=False)
        volume=TensorTSDFVolume(.005,.02,block_count=100)
        for _ in range(4):volume.integrate(rgbd,o3d.camera.PinholeCameraIntrinsic(40,30,60,60,20,15),np.eye(4))
        cloud=volume.extract_point_cloud()
        self.assertGreater(len(cloud.points),100)
        self.assertAlmostEqual(float(np.median(np.asarray(cloud.points)[:,2])),.2,delta=.002)
        np.testing.assert_allclose(np.median(np.asarray(cloud.colors),axis=0),np.array([40,100,180])/255,atol=1/255)
        self.assertGreater(len(volume.extract_triangle_mesh().triangles),100)


if __name__=="__main__":unittest.main()
