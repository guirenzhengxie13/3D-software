import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from reconstruction_probe.lod_cache import load_lod_cache,include_original_vertices
from reconstruction_probe.offline import file_sha256


class SpatialCacheTests(unittest.TestCase):
    def fixture(self,root):
        source=root/'source.ply';rows=np.zeros(5,dtype=[('x','<f8'),('y','<f8'),('z','<f8'),('red','u1'),('green','u1'),('blue','u1')])
        rows['x']=np.arange(5);rows['z']=500;rows['red']=10;rows['green']=20;rows['blue']=30
        header='ply\nformat binary_little_endian 1.0\nelement vertex 5\nproperty double x\nproperty double y\nproperty double z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n'
        source.write_bytes(header.encode()+rows.tobytes());cache=root/'cache';cache.mkdir();ids=np.array([1,4],np.uint64)
        np.savez_compressed(cache/'preview-data.npz',original_vertex_ids=ids,xyz_mm=np.array([[1,0,500],[4,0,500]],np.float32),rgb=np.tile(np.array([10,20,30],np.uint8),(2,1)))
        meta=dict(format_version=1,unit='mm',kind='spatial_original_vertex_preview',source_sha256=file_sha256(source),source_vertex_count=5,preview_points=2,
            output_sha256={'preview-data.npz':file_sha256(cache/'preview-data.npz')})
        (cache/'summary.json').write_text(json.dumps(meta),encoding='utf-8');return source,cache

    def test_cache_retains_original_rows_instead_of_renumbering_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,cache=self.fixture(Path(temporary));data=load_lod_cache(cache,source,2,verify_original_rows=True)
            np.testing.assert_array_equal(data['ids'],[1,4])
            with self.assertRaisesRegex(ValueError,'budget'):load_lod_cache(cache,source,1)

    def test_changed_source_and_changed_payload_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,cache=self.fixture(Path(temporary));original=source.read_bytes();source.write_bytes(original+b'changed')
            with self.assertRaisesRegex(ValueError,'source file changed'):load_lod_cache(cache,source)
            source.write_bytes(original)
            with (cache/'preview-data.npz').open('ab') as stream:stream.write(b'changed')
            with self.assertRaisesRegex(ValueError,'payload changed'):load_lod_cache(cache,source)

    def test_original_coordinate_crosscheck_detects_an_incorrect_cached_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,cache=self.fixture(Path(temporary));payload=cache/'preview-data.npz'
            with np.load(payload,allow_pickle=False) as saved:arrays={name:saved[name].copy() for name in saved.files}
            arrays['xyz_mm'][0,0]=99;np.savez_compressed(payload,**arrays)
            path=cache/'summary.json';meta=json.loads(path.read_text(encoding='utf-8'));meta['output_sha256']['preview-data.npz']=file_sha256(payload);path.write_text(json.dumps(meta),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'original PLY rows'):load_lod_cache(cache,source,verify_original_rows=True)

    def test_earlier_landmarks_can_be_added_without_renumbering_or_silent_budget_growth(self):
        with tempfile.TemporaryDirectory() as temporary:
            source,cache=self.fixture(Path(temporary));preview=load_lod_cache(cache,source)
            result=include_original_vertices(preview,source,[1,3],3)
            np.testing.assert_array_equal(result['ids'],[1,4,3]);np.testing.assert_array_equal(result['xyz'][-1],[3,0,500])
            self.assertEqual(len(preview['ids']),2)
            with self.assertRaisesRegex(ValueError,'budget'):include_original_vertices(preview,source,[3],2)


if __name__=='__main__':unittest.main()
