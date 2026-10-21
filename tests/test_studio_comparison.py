import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from reconstruction_probe.lod_cache import write_vertex_preview_ply
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('comparison_builder',ROOT/'scripts/build_studio_comparison.py')
builder=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(builder)


class SharedComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.model=self.root/'points.ply'
        write_vertex_preview_ply(self.model,np.array([[0,0,10],[10,0,10],[0,10,10]],np.float32),np.full((3,3),100,np.uint8),np.arange(3))

    def test_generated_page_uses_shared_viewer_original_ids_and_safe_embedded_json(self):
        output=self.root/'review.html'
        label='x</script><script>unexpected()</script>'
        with patch.object(builder,'PathMapper',return_value=PathMapper(self.root)):
            data=builder.build([label+'='+str(self.model),'reference='+str(self.model)],output,'known saved mm',budget=100)
        page=output.read_text(encoding='utf-8')
        embedded=re.search(r'<script id="comparison-data" type="application/json">(.*?)</script>',page,re.S)[1]
        parsed=json.loads(embedded)
        self.assertNotIn('<',embedded);self.assertEqual(parsed['clouds'][0]['label'],label)
        self.assertEqual(parsed['viewer_sources_sha256']['web/studio/point_viewer.js'],file_sha256(ROOT/'web/studio/point_viewer.js'))
        self.assertIn((ROOT/'web/studio/point_viewer.js').read_text(encoding='utf-8'),page)
        self.assertIn('Canvas兼容显示',page);self.assertIn('RegistrationMath',page)
        self.assertEqual(data['boundsMm'],[[0.,0.,10.],[10.,10.,10.]])
        for row in parsed['clouds']:
            import base64
            np.testing.assert_array_equal(np.frombuffer(base64.b64decode(row['ids']),'<u4'),[0,1,2])

    def test_comparison_requires_explicit_common_frame_and_fresh_output(self):
        specs=['one='+str(self.model),'two='+str(self.model)]
        with patch.object(builder,'PathMapper',return_value=PathMapper(self.root)):
            with self.assertRaises(ValueError):builder.build(specs,self.root/'review.html','')
            with self.assertRaises(ValueError):builder.build(specs[:1],self.root/'review.html','saved')
            p=self.root/'old.html';p.write_text('keep')
            with self.assertRaises(ValueError):builder.build(specs,p,'saved')
            self.assertEqual(p.read_text(),'keep')


if __name__=='__main__':unittest.main()
