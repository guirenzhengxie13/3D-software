import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

from reconstruction_probe.fusion_settings import effective_truncation_mm,executed_fusion_settings


class EffectiveFusionSettingsTests(unittest.TestCase):
    def test_tensor_honors_two_three_four_and_eight_voxel_requests(self):
        for factor in [2,3,4,8]:self.assertAlmostEqual(effective_truncation_mm(.8*factor,.8,'tensor'),.8*factor)
        self.assertEqual(effective_truncation_mm(1.2,.6,'uniform'),2.4)
        self.assertEqual(effective_truncation_mm(3.,.6,'uniform'),3.)
        for args in [(float('nan'),.6,'tensor'),(1.2,True,'tensor'),(.6,.6,'tensor'),(1.2,.6,'unknown')]:
            with self.subTest(args=args),self.assertRaises(ValueError):effective_truncation_mm(*args)

    def test_actual_settings_come_from_executed_report_not_requested_values(self):
        report=dict(tsdf_backend='tensor',requested_truncation_mm=1.6,voxel_mm=.8,sdf_truncation_mm=3.2,depth_edge_threshold_mm=3.,tensor_diagnostics=dict(extraction_weight_threshold=3.,voxel_m=.0008,truncation_voxel_multiplier=4.))
        self.assertEqual(executed_fusion_settings(report)['truncation_mm'],3.2)
        with self.assertRaises(ValueError):executed_fusion_settings({**report,'tsdf_backend':'uniform'})
        with self.assertRaises(ValueError):executed_fusion_settings({**report,'tensor_diagnostics':{**report['tensor_diagnostics'],'truncation_voxel_multiplier':2.}})

    def test_actual_metric_plane_runs_two_voxel_band_without_silent_floor(self):
        scripts=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(scripts))
        try:from reconstruct_scans import reconstruct
        finally:sys.path.remove(str(scripts))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);decoded=root/'decoded';decoded.mkdir();source=root/'original';source.mkdir();n=4
            index=dict(scan_id='synthetic_plane',source_directory=str(source),optical_to_pose_axes=[1,1,1],frames=[dict(id=i) for i in range(n)],intrinsics=dict(Pl=dict(width=40,height=30,K=[[60,0,20],[0,60,15],[0,0,1]])))
            (decoded/'index.json').write_text(json.dumps(index),encoding='utf-8')
            for i in range(n):
                d=decoded/f'frame_{i:010d}';d.mkdir();np.savez_compressed(d/'frame.npz',depth_mm=np.full((30,40),203,np.float32),rgba=np.full((1200,4),100,np.uint8))
            report=reconstruct(decoded,root/'result',2.,4.,3.,1,True,pose_overrides={i:np.eye(4) for i in range(n)},evaluate_vendor=False,bounds_override_mm=[[-80,-60,180],[80,60,220]],tsdf_backend='tensor',tsdf_weight_threshold=3.,frame_depth_filter=lambda depth,pose,rid:(depth,0))
            self.assertEqual(report['requested_truncation_mm'],4.);self.assertEqual(report['sdf_truncation_mm'],4.);self.assertEqual(report['tensor_diagnostics']['truncation_voxel_multiplier'],2.)
            self.assertGreater(report['quality']['point_count'],100);self.assertEqual(report['integrated_frames'],n)


if __name__=='__main__':unittest.main()
