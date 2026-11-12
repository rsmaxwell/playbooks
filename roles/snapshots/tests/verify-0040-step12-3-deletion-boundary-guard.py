#!/usr/bin/env python3
"""0040 Step 12.3: fail-closed deletion boundary regression."""
import ast
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
SOURCE = Path(__file__).resolve().parents[1] / 'files' / 'btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('snapshot_manager_0040', SOURCE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
class Tests(unittest.TestCase):
    def test_absent_marker(self):
        with tempfile.TemporaryDirectory() as td:
            module.receiver_refuse_unfinished_transfer(Path(td))
    def test_existing_marker_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / '.agreed-parent-transfer-pending.json').write_text('{}')
            with self.assertRaisesRegex(module.SnapshotError, 'unfinished agreed-parent transfer'):
                module.receiver_refuse_unfinished_transfer(Path(td))
    def test_dangling_symlink_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / '.agreed-parent-transfer-pending.json').symlink_to('missing')
            with self.assertRaises(module.SnapshotError):
                module.receiver_refuse_unfinished_transfer(Path(td))
    def test_deletion_checks_before_inventory_and_before_journal(self):
        source = SOURCE.read_text()
        fn = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'receiver_delete_one_locked')
        body = ast.get_source_segment(source, fn)
        self.assertEqual(body.count('receiver_refuse_unfinished_transfer(state)'), 2)
        self.assertLess(body.index('receiver_refuse_unfinished_transfer(state)'), body.index('entries = receiver_inventory(config)'))
        self.assertLess(body.rindex('receiver_refuse_unfinished_transfer(state)'), body.index('receiver_journal_write(state, record)'))
    def test_live_receiver_prune_remains_disabled(self):
        with self.assertRaisesRegex(module.SnapshotError, 'receiver pruning blocked'):
            module.receiver_guarded_prune(None)
if __name__ == '__main__':
    unittest.main(verbosity=2)
