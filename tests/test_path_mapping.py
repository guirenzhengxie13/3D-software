import json
from pathlib import Path
import tempfile
import unittest

from reconstruction_probe.path_mapping import CAPTURE_ROOT, PROJECT_ROOTS, PathMapper


class HistoricalPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mapper = PathMapper(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_english_chinese_and_capture_roots_map_to_workspace(self):
        for old in PROJECT_ROOTS:
            self.assertEqual(self.mapper.resolve(old + r'\reports\sample.json'), self.root/'reports/sample.json')
        self.assertEqual(self.mapper.resolve(CAPTURE_ROOT + r'\uuid\pointclouds\fuse.ply'),
                         self.root/'data/revo-scan-projects/uuid/pointclouds/fuse.ply')
        self.assertEqual(self.mapper.resolve(r'g:/PROJECT/REVOPOINT SOFTWARE/reports/sample.json'),
                         self.root/'reports/sample.json')

    def test_boundaries_reject_parent_sibling_unknown_drive_and_outside_native_path(self):
        for text in [PROJECT_ROOTS[0] + r'\..\secret.txt',
                     PROJECT_ROOTS[0] + r'-other\reports\sample.json',
                     r'Z:\unknown\reports\sample.json', '../secret.txt', str(self.root.parent/'secret.txt')]:
            with self.subTest(path=text), self.assertRaises(ValueError):
                self.mapper.resolve(text)

    def test_mapping_copies_records_and_preserves_digest_values(self):
        old = PROJECT_ROOTS[0] + r'\reports\sample.json'
        original = dict(source=dict(path=old), input_sha256={old:'same-raw-sha'}, note='unchanged')
        before = json.dumps(original)
        mapped = self.mapper.record(original)
        self.assertEqual(mapped['source']['path'],str(self.root/'reports/sample.json'))
        self.assertEqual(mapped['input_sha256'],{str(self.root/'reports/sample.json'):'same-raw-sha'})
        self.assertEqual(json.dumps(original),before)

    def test_optional_config_maps_only_named_roots_to_contained_targets(self):
        config=self.root/'config/path-mapping.local.json';config.parent.mkdir()
        config.write_text(json.dumps(dict(mappings=[dict(source=r'R:\archive',target='data/archive')])),encoding='utf-8')
        self.assertEqual(PathMapper(self.root).resolve(r'R:\archive\one.ply'),self.root/'data/archive/one.ply')
        config.write_text(json.dumps(dict(mappings=[dict(source=r'R:\archive',target='../escape')])),encoding='utf-8')
        with self.assertRaises(ValueError):PathMapper(self.root)


if __name__=='__main__':unittest.main()
