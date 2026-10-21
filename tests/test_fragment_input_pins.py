import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reconstruction_probe.fragment_plan import load_fragment_inputs
from reconstruction_probe.offline import file_sha256
from reconstruction_probe.path_mapping import PathMapper


class FragmentInputPinTests(unittest.TestCase):
    def test_expected_pin_is_preserved_if_shared_file_changes_after_its_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);mapper=PathMapper(root)
            source=root/'frame.npz';source.write_bytes(b'original saved depth fixture')
            expected=file_sha256(source);index=root/'index.json';index.write_bytes(b'{"scan_id":"A","frames":[]}')
            plan=root/'plan.json';plan.write_text(json.dumps(dict(input_sha256={str(source):expected})),encoding='utf-8')
            parsed_bytes=plan.read_bytes()
            def hash_then_replace(path):
                observed=file_sha256(path)
                source.write_bytes(b'new network revision after successful hash check')
                return observed
            with patch('reconstruction_probe.fragment_plan.file_sha256',side_effect=hash_then_replace):
                loaded,index_data,pins=load_fragment_inputs(plan,index,mapper)
            self.assertEqual(pins[str(source)],expected)
            self.assertNotEqual(file_sha256(source),pins[str(source)],'post-integration verification must catch the new revision')
            self.assertEqual(pins[str(plan)],hashlib.sha256(parsed_bytes).hexdigest())
            self.assertEqual(index_data['scan_id'],'A')

    def test_stale_source_or_conflicting_index_pin_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);mapper=PathMapper(root)
            index=root/'index.json';index.write_text('{"scan_id":"A"}')
            plan=root/'plan.json';source=root/'source';source.write_bytes(b'data')
            for pins in [{str(source):'0'*64},{str(index):'0'*64},{str(source):None}]:
                plan.write_text(json.dumps(dict(input_sha256=pins)),encoding='utf-8')
                with self.subTest(pins=pins),self.assertRaises(ValueError):load_fragment_inputs(plan,index,mapper)


if __name__=='__main__':unittest.main()
