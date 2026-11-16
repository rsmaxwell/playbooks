#!/usr/bin/env python3
"""0049 source/fixture regression. Read-only; no Btrfs or systemd modifications."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / 'snapshots' / 'files'
REPL = ROOT / 'btrfs-replication'


def load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


diaries = load(SNAPSHOTS / 'diaries-backup-status.py', 'diaries_0049')
btrfs = load(SNAPSHOTS / 'btrfs-backup-status.py', 'btrfs_0049')
manager = load(SNAPSHOTS / 'btrfs-snapshot-manager.py', 'manager_0049')
replication = load(REPL / 'files' / 'btrfs-replication.py', 'replication_0049')

S1 = '20261114-014500Z'
S2 = '20261115-014500Z'
S3 = '20261116-014500Z'
UUID = '11111111-1111-1111-1111-111111111111'


class ReportTests(unittest.TestCase):
    def test_diaries_report_has_only_application_data_and_aligns_table(self):
        rows = [
            {'logicalDataset': 'production', 'backupId': S1,
             'firstRetainedSnapshot': S1, 'lastRetainedSnapshot': S2,
             'snapshots': 13, 'status': 'verified'},
            {'logicalDataset': 'production extra long', 'backupId': S2,
             'firstRetainedSnapshot': S2, 'lastRetainedSnapshot': S3,
             'snapshots': 2, 'status': 'conflict'},
        ]
        with patch.object(diaries, 'inspect_history', return_value={'backups': rows, 'warnings': []}):
            outcome = diaries.report(SimpleNamespace(history='/fixture', config='/fixture', limit=2))
        self.assertEqual(outcome['health'], 'degraded')
        self.assertEqual(outcome['distinctBackups'], 2)
        self.assertEqual(outcome['retainedOccurrences'], 15)
        self.assertNotIn('snapshot', outcome)
        self.assertNotIn('replicationPreflight', outcome)
        self.assertNotIn('offsite', outcome)
        self.assertNotIn('lastVerifiedPull', outcome)
        out = io.StringIO()
        with contextlib.redirect_stdout(out): diaries.display(outcome)
        text = out.getvalue()
        self.assertIn('RECENT DIARIES BACKUPS', text)
        self.assertIn('Logical dataset', text)
        self.assertIn('Snapshots', text)
        self.assertIn('production extra long', text)
        self.assertNotIn('QGROUP', text)
        self.assertNotIn('PUSH', text)

    def test_diaries_empty_report_has_labelled_empty_table(self):
        with patch.object(diaries, 'inspect_history', return_value={'backups': [], 'warnings': []}):
            outcome = diaries.report(SimpleNamespace(history='-', config='-', limit=5))
        self.assertIsNone(outcome['latest'])
        out = io.StringIO()
        with contextlib.redirect_stdout(out): diaries.display(outcome)
        self.assertIn('No retained backups found', out.getvalue())

    def test_diaries_json_is_indented_and_errors_use_exit_2(self):
        with patch.object(diaries, 'inspect_history', return_value={'backups': [], 'warnings': []}):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(diaries.main(['--json']), 0)
            self.assertIn('\n  "component"', out.getvalue())
            self.assertEqual(json.loads(out.getvalue())['health'], 'healthy')
        with patch.object(diaries, 'inspect_history', side_effect=RuntimeError('broken')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(diaries.main(['--json']), 2)
            self.assertEqual(json.loads(out.getvalue())['health'], 'error')

    def _btrfs_fixture(self, role, local_only=False, peer_fail=False):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'manager.json'
            config.write_text(json.dumps({'mode': role, 'sources': [], 'verification': {'required': False}}))
            calls = []
            def fake_execute(argv, timeout=45, *, env=None):
                calls.append((argv, env))
                if argv[-1] == 'status' and argv[0] == '/manager':
                    return {'ok': True, 'stdout': 'snapshot_root=/fixtures\nqgroups_status=ok\nqgroups_total=12\nretention=hourly:48\ncomplete_timestamp_sets=2;incomplete_timestamp_sets=0'}
                if argv[-1] == 'list':
                    return {'ok': True, 'stdout': 'BTRFS SNAPSHOT INVENTORY\n'+S2+'  COMPLETE @data\n'+S3+'  COMPLETE @data'}
                if argv[0] == '/replication':
                    if argv[1] == 'sender':
                        self.assertIsNotNone(env)
                        self.assertEqual(env.get('BTRFS_REPLICATION_IDENTITY_MODE'), 'dedicated')
                    else:
                        self.assertIsNone(env)
                    if peer_fail:
                        return {'ok': False, 'error': 'no SSH connectivity', 'stdout': ''}
                    if argv[1] == 'receiver':
                        return {'ok': True, 'stdout': json.dumps({'state': {'parent': {'timestamp': S2, 'uuid': UUID}}})}
                    return {'ok': True, 'stdout': json.dumps({
                        'receiver_parent_verified': True, 'relation': 'equal',
                        'receiver': {'parent': {'timestamp': S2, 'uuid': UUID}},
                        'preflight': {'action': 'up-to-date', 'source': None, 'parent': S2}})}
                raise AssertionError(argv)
            args = SimpleNamespace(config=str(config), manager='/manager', replication='/replication',
                                   local_only=local_only, verbose=True)
            with patch.object(btrfs, 'execute', side_effect=fake_execute), \
                 patch.object(btrfs, 'local_parent', return_value={
                    'state': 'available', 'parent': {'timestamp': S2, 'uuid': UUID}, 'prior': None}), \
                 patch.object(btrfs, 'service_status', return_value={'state': 'available', 'properties': {'ActiveState':'active'}}):
                data = btrfs.report(args)
            return data, calls

    def test_local_only_skips_sender_ssh_even_when_remote_is_unavailable(self):
        data, calls = self._btrfs_fixture('source', local_only=True, peer_fail=True)
        self.assertEqual(data['role'], 'source')
        self.assertEqual(data['replication']['remote']['state'], 'not_checked')
        self.assertEqual(data['health'], 'healthy')
        self.assertFalse(any('/replication' in cmd for cmd, env in calls))
        self.assertTrue(data['limits']['remoteChecked'] is False)
        self.assertNotIn('lastVerifiedTransfer', data['collection'])
        self.assertNotIn('replication', data['collection'])

    def test_qgroup_warning_degrades_infrastructure_status(self):
        original = btrfs.parse_manager_status
        def warning(output):
            values = original(output)
            values['qgroups_status'] = 'warning'
            return values
        with patch.object(btrfs, 'parse_manager_status', side_effect=warning):
            data, _ = self._btrfs_fixture('source', local_only=True)
        self.assertEqual(data['health'], 'degraded')
        self.assertTrue(any('qgroup' in issue for issue in data['issues']))

    def test_source_remote_success_and_failure_have_distinct_health(self):
        data, calls = self._btrfs_fixture('source')
        self.assertEqual(data['health'], 'healthy')
        self.assertEqual(data['replication']['remote']['state'], 'verified')
        self.assertTrue(any(cmd[-2:] == ['sender', 'status'] for cmd, env in calls))
        failed, _ = self._btrfs_fixture('source', peer_fail=True)
        self.assertEqual(failed['health'], 'degraded')
        self.assertEqual(failed['replication']['remote']['state'], 'unavailable')
        self.assertEqual(failed['limits']['lastVerifiedTransfer'], 'unknown: no independent transfer receipt')

    def test_receiver_has_no_collection_section_or_ssh_calls(self):
        data, calls = self._btrfs_fixture('receiver')
        self.assertEqual(data['role'], 'receiver')
        self.assertIsNone(data['collection'])
        self.assertEqual(data['replication']['receiver']['state'], 'available')
        self.assertFalse(any(cmd[-2:] == ['sender', 'status'] for cmd, env in calls))
        out = io.StringIO()
        with contextlib.redirect_stdout(out): btrfs.display(data)
        self.assertNotIn('BACKUP COLLECTION', out.getvalue())
        self.assertIn('SCHEDULED OPERATIONS', out.getvalue())
        self.assertIn('FILESYSTEM QGROUP HEALTH', out.getvalue())

    def test_host_json_is_pretty_and_machine_parseable(self):
        data, _ = self._btrfs_fixture('receiver')
        encoded = json.dumps(data, indent=2, sort_keys=True)
        self.assertEqual(json.loads(encoded)['role'], 'receiver')
        self.assertIn('\n  "role"', encoded)

    def test_bad_config_fails_closed(self):
        data = btrfs.report(SimpleNamespace(config='/nonexistent-0049-config', manager='-',replication='-',local_only=True,verbose=False))
        self.assertEqual(data['health'], 'error')

    def test_table_does_not_truncate_unicode_or_identifiers(self):
        identifier = 'uuid-'+'0'*40
        result = btrfs.table(('Name', 'Count'), [('é' * 25+identifier, 1200), ('test', 3)], numeric=(1,))
        self.assertIn(identifier, result)
        self.assertIn('1200', result)
        self.assertEqual(len(result.splitlines()), 4)


class SnapshotCliTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(mode='receiver', lock_path=Path('/fixture/manager.lock'),writer_lock_path=None)
        self.lock = Mock()
        self.ex = contextlib.ExitStack()
        self.ex.enter_context(patch.object(manager, 'require_root'))
        self.ex.enter_context(patch.object(manager, 'load_config', return_value=self.config))
        self.lock_provider = self.ex.enter_context(patch.object(manager, 'with_lock', return_value=self.lock))
        self.preview = self.ex.enter_context(patch.object(manager, 'receiver_simple_plan', return_value={
            'parent': {'timestamp': S2}, 'prior': None, 'keep': [], 'candidates': [], 'identity': {},
            'historical_receipts': [], 'historical_receipts_on_candidates': [],
            'historical_receipts_orphaned': [], 'holds': [], 'executable': True}))
        self.prune = self.ex.enter_context(patch.object(manager, 'receiver_simple_prune', return_value=0))
        self.ex.enter_context(patch.object(manager, 'receiver_simple_print_plan'))

    def tearDown(self):
        self.ex.close()

    def test_receiver_preview_uses_existing_shared_lock_and_never_deletes(self):
        self.assertEqual(manager.main(['prune', '--dry-run']), 0)
        self.prune.assert_not_called()
        self.preview.assert_called_once()
        self.lock_provider.assert_called_once_with(self.config.lock_path, shared=True, require_existing=True)

    def test_receiver_delete_requires_explicit_bound(self):
        self.assertEqual(manager.main(['prune']), 2)
        self.prune.assert_not_called()
        self.assertEqual(manager.main(['prune', '--max-delete', '10']), 0)
        self.prune.assert_called_once_with(self.config, max_delete=10)

    def test_receiver_create_is_refused(self):
        self.assertEqual(manager.main(['create']), 2)

    def test_old_receiver_subcommands_are_no_longer_accepted(self):
        for cmd in ('receiver-simple-plan', 'receiver-simple-prune', 'receiver-prune', 'run'):
            with patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit):
                    manager.main([cmd])

    def test_source_bounded_prune_remains_distinct(self):
        self.config.mode = 'source'
        with patch.object(manager, 'prune', return_value=0) as called:
            self.assertEqual(manager.main(['prune', '--max-delete', '32']), 0)
            called.assert_called_once_with(self.config, False, 32)


class DeploymentSourceTests(unittest.TestCase):
    def test_protocol_implementation_diff_is_only_executable_name_and_pretty_status(self):
        old = (REPL / 'files/btrfs-simplified-replication.py').read_text()
        new = (REPL / 'files/btrfs-replication.py').read_text()
        expected = old.replace("INSTALL = '/usr/local/bin/btrfs-simplified-replication'", "INSTALL = '/usr/local/bin/btrfs-replication'")
        # 0049 presentation-only help text changes; the replication protocol remains unchanged.
        expected = expected.replace('"""0040-FEAT: simple native Btrfs agreed-parent replication (opt-in).',
                               '"""Native Btrfs agreed-parent snapshot replication (sender and receiver).')
        expected = expected.replace('print(json.dumps(sender_readonly_status(), sort_keys=True))',
                                    'print(json.dumps(sender_readonly_status(), sort_keys=True, indent=2))')
        self.assertEqual(new, expected)
        self.assertIn("print(json.dumps(result, sort_keys=True), flush=True)", new)  # receiver protocol unchanged

    def test_0041_dedicated_user_and_sudoers_preserved(self):
        unit = (REPL / 'templates/btrfs-push.service.j2').read_text()
        sudoers = (REPL / 'templates/btrfs-0041-service-sudoers.j2').read_text()
        source_wrapper = (REPL / 'files/btrfs-replication-sender-cycle-0041.sh').read_text()
        receiver_gate = (REPL / 'files/btrfs-replication-receiver-gate-0041.py').read_text()
        self.assertIn('User=btrfs-send', unit)
        self.assertIn('ExecStart=/usr/bin/sudo -n /usr/local/libexec/btrfs-replication-sender-cycle-0041', unit)
        self.assertNotIn('NOPASSWD:ALL', sudoers)
        self.assertIn('btrfs-replication sender cycle', source_wrapper)
        self.assertIn("RUNTIME = '/usr/local/bin/btrfs-replication'", receiver_gate)
        self.assertNotIn('btrfs-simplified-replication', receiver_gate)

    def test_unit_cutover_disables_old_before_new_and_removes_old(self):
        source = (REPL / 'tasks/source-scheduling.yaml').read_text()
        receiver = (REPL / 'tasks/receiver-retention.yaml').read_text()
        retirement = (REPL / 'tasks/retire-0049-interfaces.yaml').read_text()
        self.assertLess(source.index('Stop and disable old push timer'),
                        source.index('is-active --quiet btrfs-native-push.service'))
        self.assertLess(source.index('is-active --quiet btrfs-native-push.service'),
                        source.index('Apply explicit push schedule state'))
        self.assertLess(receiver.index('Stop and disable old receiver prune timer'),
                        receiver.index('is-active --quiet btrfs-receiver-simple-prune.service'))
        self.assertLess(receiver.index('is-active --quiet btrfs-receiver-simple-prune.service'),
                        receiver.index('Enforce explicit receiver retention timer state'))
        self.assertIn('btrfs-native-push.timer', retirement)
        self.assertIn('btrfs-receiver-simple-prune.timer', retirement)
        self.assertIn('state: absent', retirement)
        self.assertIn('btrfs_push_schedule_enabled', source)
        self.assertIn('btrfs_receiver_prune_max_delete', (REPL/'templates/btrfs-receiver-prune.service.j2').read_text())

    def test_inventory_compatibility_is_explicit(self):
        text = (REPL / 'defaults/main.yaml').read_text()
        self.assertIn('btrfs_push_schedule_enabled:', text)
        self.assertIn('btrfs_native_push_schedule_enabled | default(false)', text)
        self.assertIn('btrfs_replication_install_enabled:', text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
