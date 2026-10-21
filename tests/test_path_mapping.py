import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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

    def test_original_machine_can_read_native_capture_but_cannot_write_there(self):
        with tempfile.TemporaryDirectory() as raw:
            capture=Path(raw).resolve()
            with patch.object(PathMapper,'_native_capture_root',return_value=capture):
                mapper=PathMapper(self.root)
            source=CAPTURE_ROOT+r'\uuid\raw_preview.ply'
            self.assertEqual(mapper.resolve(source),capture/'uuid/raw_preview.ply')
            self.assertEqual(mapper.record({'source_directory':CAPTURE_ROOT+r'\uuid'})['source_directory'],str(capture/'uuid'))
            with self.assertRaises(ValueError):mapper.resolve_output(source)
            with self.assertRaises(ValueError):mapper.resolve(str(capture.parent/'unrelated.ply'))
            self.assertEqual(mapper.resolve_output('reports/new.json'),self.root/'reports/new.json')

    def test_migrated_machine_keeps_workspace_capture_mapping(self):
        with patch.object(PathMapper,'_native_capture_root',return_value=None):
            mapper=PathMapper(self.root)
        self.assertEqual(mapper.resolve(CAPTURE_ROOT+r'\uuid'),self.root/'data/revo-scan-projects/uuid')

    def test_explicit_capture_copy_config_overrides_native_default(self):
        config=self.root/'config/path-mapping.local.json';config.parent.mkdir()
        config.write_text(json.dumps(dict(mappings=[dict(source=CAPTURE_ROOT,target='data/chosen-copy')])),encoding='utf-8')
        with tempfile.TemporaryDirectory() as raw, patch.object(PathMapper,'_native_capture_root',return_value=Path(raw).resolve()):
            mapper=PathMapper(self.root)
        self.assertEqual(mapper.resolve(CAPTURE_ROOT+r'\uuid'),self.root/'data/chosen-copy/uuid')

    def test_configured_external_capture_is_readable_but_not_an_output_root(self):
        config=self.root/'config/path-mapping.local.json';config.parent.mkdir()
        with tempfile.TemporaryDirectory() as raw:
            capture=Path(raw).resolve()
            config.write_text(json.dumps(dict(read_mappings=[dict(source=CAPTURE_ROOT,target=str(capture))])),encoding='utf-8')
            mapper=PathMapper(self.root);mapped=mapper.resolve(CAPTURE_ROOT+r'\uuid\frame.bin')
            self.assertEqual(mapped,capture/'uuid/frame.bin')
            with self.assertRaises(ValueError):mapper.resolve_output(CAPTURE_ROOT+r'\uuid\frame.bin')
            with self.assertRaises(ValueError):mapper.resolve(str(capture.parent/'unlisted.bin'))

    def test_colliding_historical_hash_keys_cannot_silently_drop_a_pin(self):
        with self.assertRaisesRegex(ValueError,'conflicting'):
            self.mapper.record({PROJECT_ROOTS[0]+r'\reports\x.json':'one',PROJECT_ROOTS[1]+r'\reports\x.json':'two'})


if __name__=='__main__':unittest.main()
