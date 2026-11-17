#!/usr/bin/env python3
"""Permanent 0050 source/deployment regressions; does not access real backup hosts."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

PLAYBOOKS = Path(__file__).resolve().parents[3]
REPL = PLAYBOOKS / "roles" / "btrfs-replication"
HISTORY = PLAYBOOKS / "roles" / "snapshots" / "files" / "diaries-backup-history.py"

spec = importlib.util.spec_from_file_location("diaries_history_0050", HISTORY)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class DeploymentContract(unittest.TestCase):
    def test_receiver_template_is_readonly_additive(self):
        text = (REPL / "templates" / "btrfs-receiver-manager.json.j2").read_text()
        self.assertIn('"verification": {"required": false}', text)
        self.assertIn('"diaries_history": {', text)
        self.assertIn('"marker_relative_path": "backup/.diaries-snapshot-verified.json"', text)
        self.assertIn('"dataset_relative_path": "backup/pluto/diaries-backup"', text)
        self.assertIn('"source_name": "@data"', text)
        self.assertIn('"manifest_tool": "/usr/local/lib/diaries-backup/complete-dataset-manifest.py"', text)
        self.assertIn('"receiver_prune_enabled":', text)
        self.assertIn('"checkpoint_holds":', text)

    def test_only_receiver_installs_shared_commands_and_verifier(self):
        tasks = yaml.safe_load((REPL / 'tasks' / 'receiver-diaries-history.yaml').read_text())
        self.assertEqual(len(tasks), 3)
        for task in tasks:
            op = task['ansible.builtin.copy'] if 'ansible.builtin.copy' in task else task['ansible.builtin.file']
            self.assertEqual(op['owner'], 'root')
            self.assertEqual(op['group'], 'root')
            self.assertIn("btrfs_native_endpoint_role == 'receiver'", task['when'])
            self.assertTrue(any('or (btrfs_receiver_retention_install_enabled | bool)' in clause for clause in task['when']))
            self.assertEqual(op['mode'], '0755')
        text = (REPL / 'tasks' / 'native.yaml').read_text()
        self.assertIn('import_tasks: receiver-diaries-history.yaml', text)
        self.assertIn('import_tasks: receiver-retention.yaml', text)
        self.assertLess(text.index('import_tasks: receiver-retention.yaml'), text.index('import_tasks: receiver-diaries-history.yaml'))
        self.assertEqual(tasks[2]['ansible.builtin.copy']['dest'], '/usr/local/sbin/{{ item.dest }}')
        self.assertEqual({item['dest'] for item in tasks[2]['loop']},
                         {'diaries-backup-status', 'diaries-backup-history'})
        self.assertIn('/roles/diaries/files/sync/scripts/complete-dataset-manifest.py',
                      tasks[1]['ansible.builtin.copy']['src'])
    def test_receiver_config_requires_explicit_local_canonical_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repository = root / 'receiver'
            (repository / '@data').mkdir(parents=True)
            cfg = root / 'manager.json'
            raw = {
                'mode': 'receiver', 'snapshot_root': str(repository),
                'sources': [{'name': '@data', 'snapshot_directory': str(repository / '@data')}],
                'verification': {'required': False},
                'diaries_history': {
                    'enabled': True, 'source_name': '@data',
                    'dataset_relative_path': 'backup/pluto/diaries-backup',
                    'marker_relative_path': 'backup/.diaries-snapshot-verified.json',
                    'manifest_tool': '/usr/local/lib/diaries-backup/complete-dataset-manifest.py',
                },
            }
            def load():
                cfg.write_text(json.dumps(raw), encoding='utf-8')
                return module.load_config(cfg)
            self.assertEqual(load().snapshot_root, repository)
            raw['verification']['required'] = True
            with self.assertRaises(module.HistoryError): load()
            raw['verification']['required'] = False
            raw['diaries_history']['enabled'] = False
            with self.assertRaises(module.HistoryError): load()
            raw['diaries_history']['enabled'] = True
            raw['sources'][0]['snapshot_directory'] = str(root / 'other')
            with self.assertRaises(module.HistoryError): load()
            raw['sources'][0]['snapshot_directory'] = str(repository / '@data')
            raw['diaries_history']['marker_relative_path'] = '../outside'
            with self.assertRaises(module.HistoryError): load()
            raw['diaries_history']['marker_relative_path'] = 'backup/.diaries-snapshot-verified.json'
            (repository / '@data').rename(repository / 'actual-data')
            (repository / '@data').symlink_to('actual-data', target_is_directory=True)
            with self.assertRaises(module.HistoryError): load()

    def test_fixed_directory_uses_explicit_schema2_verifier_mode(self):
        source = HISTORY.read_text(encoding='utf-8')
        self.assertIn('occurrence.dataset_path.name == "diaries-backup"', source)
        self.assertIn('command.append("--allow-fixed-working-root")', source)

    def test_source_0049_config_still_loads(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            config=root/'source.json'
            config.write_text(json.dumps({
                'mode':'source', 'snapshot_root':str(root/'@snapshots'),
                'sources':[{'name':'@data','path':'/unrelated/source-data'}],
                'verification':{'required':True,'source_name':'@data',
                                'dataset_relative_path':'backup/pluto/diaries-backup',
                                'marker_relative_path':'backup/.diaries-snapshot-verified.json',
                                'manifest_tool':'/usr/local/lib/diaries-backup/complete-dataset-manifest.py'},
            }),encoding='utf-8')
            self.assertEqual(module.load_config(config).source_name,'@data')


if __name__ == '__main__':
    unittest.main(verbosity=2)
