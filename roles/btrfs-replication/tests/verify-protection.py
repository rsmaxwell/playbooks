#!/usr/bin/env python3
"""Check source/receiver retention manager uses simple state and preserves old pins."""
import ast
from pathlib import Path
from types import SimpleNamespace
import tempfile
import importlib.util
import unittest
import json
import os
from unittest.mock import patch

MANAGER=Path(__file__).parents[2]/'snapshots/files/btrfs-snapshot-manager.py'
spec=importlib.util.spec_from_file_location('simplified_retention_manager',MANAGER)
m=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=m
spec.loader.exec_module(m)
U1='11111111-1111-1111-1111-111111111111'
U2='22222222-2222-2222-2222-222222222222'
A='20261030-170009Z'
B='20261101-140039Z'

class Cases(unittest.TestCase):
    @staticmethod
    def fixture_with_uid(path, uid):
        """Simulate file ownership for a single fixture, without weakening production checks.

        The snapshot manager requires root-owned state, but these regression tests
        run as a normal user on mango. Only the fixture's stat().st_uid changes.
        """
        original_stat = Path.stat

        def fixture_stat(candidate, *args, **kwargs):
            metadata = original_stat(candidate, *args, **kwargs)
            if candidate != path:
                return metadata
            fields = list(metadata)
            fields[4] = uid  # os.stat_result.st_uid
            return os.stat_result(fields)

        return patch.object(Path, "stat", fixture_stat)

    def test_missing_file_allows_pre_cutover(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(m.simplified_agreed_parent_pins(SimpleNamespace(
                mode='source',snapshot_root=Path(d),receiver_state_dir=None)),set())

    def test_pruning_planners_consult_agreed_parent_pins(self):
        """All three current prune planners must consult the protected parent set.

        A valid pin-file reader alone does not protect anything if a pruning
        path stops invoking it. This is a permanent safety invariant, unlike
        checking historical migration or retired executable names.
        """
        tree = ast.parse(MANAGER.read_text(encoding='utf-8'))
        functions = {node.name: node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in ('prune', 'receiver_plan', 'receiver_simple_plan'):
            with self.subTest(prune_planner=name):
                self.assertIn(name, functions)
                calls = (node for node in ast.walk(functions[name])
                         if isinstance(node, ast.Call))
                self.assertTrue(any(isinstance(call.func, ast.Name) and
                                    call.func.id == 'simplified_agreed_parent_pins'
                                    for call in calls),
                                f'{name} no longer consults protected parent pins')

    def test_parent_and_previous_protected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'.simple-agreed-parent.json'
            path.write_text(json.dumps({'schema':1,'parent':{'timestamp':B,'uuid':U2},
                'prior':{'timestamp':A,'uuid':U1}}))
            os.chmod(path,0o600)
            config=SimpleNamespace(mode='source',snapshot_root=Path(d),receiver_state_dir=None)
            with self.fixture_with_uid(path, 0):
                self.assertEqual(m.simplified_agreed_parent_pins(config), {A, B})

    def test_nonroot_owned_state_blocks_pruning(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'.simple-agreed-parent.json'
            path.write_text(json.dumps({'schema': 1,
                'parent': {'timestamp': B, 'uuid': U2},
                'prior': {'timestamp': A, 'uuid': U1}}))
            os.chmod(path, 0o600)
            config = SimpleNamespace(mode='source', snapshot_root=Path(d),
                                     receiver_state_dir=None)
            with self.fixture_with_uid(path, 1001):
                with self.assertRaisesRegex(m.SnapshotError, 'unsafe simplified state ownership'):
                    m.simplified_agreed_parent_pins(config)

    def test_corrupt_and_unsafe_file_blocks_pruning(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'.simple-agreed-parent.json'
            path.write_text('bad-json')
            os.chmod(path,0o600)
            config=SimpleNamespace(mode='receiver',snapshot_root=None,receiver_state_dir=Path(d))
            with self.assertRaises(m.SnapshotError): m.simplified_agreed_parent_pins(config)
            path.write_text(json.dumps({'schema':1,'parent':{'timestamp':B,'uuid':U2},'prior':None}))
            os.chmod(path,0o644)
            with self.assertRaises(m.SnapshotError): m.simplified_agreed_parent_pins(config)

if __name__=='__main__':
    unittest.main(verbosity=2)
