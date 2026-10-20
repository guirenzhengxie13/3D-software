from pathlib import Path
import tempfile
import unittest

import numpy as np

from reconstruction_probe.ply_layout import inspect_ply,map_ply_vertices,xyz_block


class PlyLayoutTests(unittest.TestCase):
    def test_binary_endianness_extra_properties_and_faces_preserve_original_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            for endian,label in [('<','little'),('>','big')]:
                dtype=np.dtype([('x',endian+'f8'),('y',endian+'f8'),('z',endian+'f8'),('red','u1')]);rows=np.zeros(3,dtype=dtype)
                rows['x']=[1,4,7];rows['y']=[2,5,8];rows['z']=[3,6,9];rows['red']=[10,20,30]
                path=Path(temporary)/(label+'.ply');header=f'ply\nformat binary_{label}_endian 1.0\ncomment units mm\nelement vertex 3\nproperty double x\nproperty double y\nproperty double z\nproperty uchar red\nelement face 1\nproperty list uchar int vertex_indices\nend_header\n'
                path.write_bytes(header.encode()+rows.tobytes()+b'\x03'+np.array([0,1,2],dtype=endian+'i4').tobytes())
                mapped,layout=map_ply_vertices(path);self.assertFalse(mapped.flags.writeable);self.assertEqual(layout.face_count,1)
                np.testing.assert_array_equal(xyz_block(mapped,1,3),[[4,5,6],[7,8,9]])
                np.testing.assert_array_equal(mapped['red'],[10,20,30]);del mapped

    def test_ascii_inspection_is_supported_but_mapping_does_not_guess_a_binary_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'ascii.ply';path.write_text('ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n1 2 3\n')
            self.assertEqual(inspect_ply(path).vertex_count,1)
            with self.assertRaises(ValueError):map_ply_vertices(path)

    def test_truncated_payload_or_duplicate_properties_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'bad.ply';header='ply\nformat binary_little_endian 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n'
            path.write_bytes(header.encode())
            with self.assertRaises(ValueError):inspect_ply(path)
            path.write_bytes(header.replace('property float y','property float x').encode()+bytes(12))
            with self.assertRaises(ValueError):inspect_ply(path)


if __name__=='__main__':unittest.main()
