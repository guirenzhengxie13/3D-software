from pathlib import Path
import tempfile
import unittest

import numpy as np

from reconstruction_probe.ply_spatial_index import build_ply_spatial_index,PlySpatialIndex


class SpatialIndexTests(unittest.TestCase):
    def fixture(self,root):
        (root/'inputs').mkdir();source=root/'inputs/source.ply';xyz=np.array([[-5,0,0],[0,0,0],[3,4,0],[5,0,0],[10,10,10],[0,0,0],[np.nan,0,0]],'<f4')
        header='ply\nformat binary_little_endian 1.0\nelement vertex 7\nproperty float x\nproperty float y\nproperty float z\nend_header\n'
        source.write_bytes(header.encode()+xyz.tobytes());return source,xyz

    def test_exact_original_ids_match_brute_force_including_boundaries_duplicates_and_nan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source,xyz=self.fixture(root);report=build_ply_spatial_index(source,root/'index',tile_mm=2.,chunk_size=2)
            self.assertEqual(report['finite_source_points'],6)
            with PlySpatialIndex(root/'index') as index:
                for center,radius in [([0,0,0],5.),([0,0,0],0.),([10,10,10],1.),([100,100,100],1.)]:
                    result=index.query_sphere(center,radius);expected=np.flatnonzero(np.sum((xyz-center)**2,axis=1)<=radius**2)
                    np.testing.assert_array_equal(result['original_vertex_ids'],expected)
                    np.testing.assert_array_equal(result['xyz_mm'],xyz[expected])

    def test_oversized_exact_queries_are_rejected_instead_of_silently_sampled(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source,_=self.fixture(root);build_ply_spatial_index(source,root/'index',tile_mm=2.)
            with PlySpatialIndex(root/'index') as index:
                with self.assertRaises(MemoryError):index.query_sphere([0,0,0],100,maximum_candidate_points=2)

    def test_changed_source_or_index_bytes_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source,_=self.fixture(root);build_ply_spatial_index(source,root/'index',tile_mm=2.)
            with (root/'index/original-vertex-ids.bin').open('ab') as stream:stream.write(b'changed')
            with self.assertRaisesRegex(ValueError,'payload changed'):PlySpatialIndex(root/'index')


if __name__=='__main__':unittest.main()
