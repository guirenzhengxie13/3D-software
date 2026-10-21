"""Check that progress syncing cannot silently replace independent remote edits."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('checkpoint', Path(__file__).resolve().parents[1] / 'scripts/sync_network_checkpoint.py')
checkpoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checkpoint)


class NetworkCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.local = Path(self.temp.name) / 'local'
        self.remote = Path(self.temp.name) / 'remote'
        self.local.mkdir(); self.remote.mkdir()
        self.local_file = self.local / 'HANDOFF.md'
        self.remote_file = self.remote / 'HANDOFF.md'
        self.local_file.write_bytes(b'new local progress')
        self.remote_file.write_bytes(b'base progress')

    def run_sync(self, name='HANDOFF.md'):
        def git(_git, *args, **kwargs):
            return subprocess.CompletedProcess(args, 0, b'base' if args[0] == 'rev-parse' else b'base progress', b'')
        with patch.object(checkpoint, 'ROOT', self.local), patch.object(checkpoint, 'git_run', side_effect=git), \
             patch('sys.argv', ['sync', '--target', str(self.remote), '--git', 'fixture', '--include', name]), \
             contextlib.redirect_stdout(io.StringIO()):
            return checkpoint.main()

    def test_success_keeps_recoverable_original_and_verifies_new_content(self):
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.remote_file.read_bytes(), b'new local progress')
        backups = list((self.remote / '.cache/continuation-sync').glob('*/before/HANDOFF.md'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'base progress')
        self.assertTrue(json.loads((self.local / '.cache/continuation-sync/latest.json').read_text())['successful'])

    def test_later_checkpoint_preserves_independent_network_edit(self):
        self.assertEqual(self.run_sync(), 0)
        self.local_file.write_bytes(b'next local progress')
        self.remote_file.write_bytes(b'independent remote progress')
        self.assertEqual(self.run_sync(), 2)
        self.assertEqual(self.remote_file.read_bytes(), b'independent remote progress')
        self.assertEqual(self.local_file.read_bytes(), b'next local progress')

    def test_missing_local_file_does_not_delete_network_file(self):
        self.local_file.unlink()
        self.assertEqual(self.run_sync(), 2)
        self.assertEqual(self.remote_file.read_bytes(), b'base progress')

    def test_relative_escape_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_sync('../outside.md')


if __name__ == '__main__':
    unittest.main()
