#!/usr/bin/env python3
"""0039-DEF: offline source, lock, parsing and mocked execution regression.

Run on mango: python3 roles/snapshots/tests/verify-btrfs-clear-stale-qgroups.py
This script never reads a production Btrfs filesystem or executes btrfs.
"""
import contextlib
import importlib.util
import io
import json
import os
from subprocess import CompletedProcess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOKS = ROOT.parents[1]
SCRIPT = ROOT / 'files/btrfs-clear-stale-qgroups.py'
SPEC = importlib.util.spec_from_file_location('qgroup_maintenance', SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

SAMPLE = '''Qgroupid    Referenced    Exclusive   Path
--------         ----         ---- ----
0/5         16.00KiB     16.00KiB <toplevel>
0/256          9.00GiB      4.00GiB @data
0/257          0.00B        0.00B <stale>
0/258          0.00B        0.00B <under deletion>
1/17           9.00GiB      4.00GiB
'''


class ParseTests(unittest.TestCase):
    def test_parses_stale_and_does_not_misclassify_pending(self):
        rows = mod.parse_qgroups(SAMPLE)
        self.assertEqual(rows['0/257'], '<stale>')
        self.assertEqual(rows['0/258'], '<under deletion>')
        self.assertNotIn('0/259', rows)

    def test_real_v663_baseline_header_and_rows(self):
        # Exact header/row shape observed on mars and backup 2026-11-09.
        sample = '''Qgroupid    Referenced    Exclusive   Path
--------    ----------    ---------   ----
0/5           16.00KiB     16.00KiB   <toplevel>
0/260        326.53GiB     16.00KiB   @data
0/262            0.00B        0.00B   <stale>
0/21336      325.94GiB     16.00KiB   <stale>
0/21342      325.94GiB     16.00KiB   @snapshots/@data/20261029-230001Z
'''
        rows = mod.parse_qgroups(sample)
        self.assertEqual(rows['0/262'], '<stale>')
        self.assertEqual(rows['0/21336'], '<stale>')
        self.assertEqual(rows['0/21342'], '@snapshots/@data/20261029-230001Z')

    def test_compact_header_still_accepted(self):
        rows = mod.parse_qgroups(SAMPLE.replace('Qgroupid    Referenced    Exclusive   Path',
                                                'qgroupid rfer excl path'))
        self.assertIn('0/257', rows)

    def test_malformed_or_unsupported_rejected(self):
        for value in ('', 'qgroupid rfer excl\n0/25 0 0',
                      'qgroupid rfer excl path\n0/25 0 0 <stale>\n0/25 0 0 <stale>',
                      'qgroupid rfer excl path\n1/25 0 0 <stale>',
                      'qgroupid rfer excl path\nrandom 0 0 <stale>'):
            with self.subTest(value=value), self.assertRaises(mod.Refused):
                mod.parse_qgroups(value)

    def test_subvolume_ids_fail_closed(self):
        from subprocess import CompletedProcess
        with patch.object(mod, 'command', return_value=CompletedProcess([], 0, 'ID 256 gen 4 top level 5 path @data\n', '')):
            self.assertEqual(mod.subvolume_ids(Path('/media/usb')), {256})
        with patch.object(mod, 'command', return_value=CompletedProcess([], 0, 'garbage\n', '')):
            with self.assertRaises(mod.Refused):
                mod.subvolume_ids(Path('/media/usb'))

    def test_pending_deletions_from_real_host_shape(self):
        sample = ('ID 21336 gen 62204 top level 0 path DELETED\n'
                  'ID 21337 gen 62207 top level 0 path DELETED\n')
        with patch.object(mod, 'command', return_value=CompletedProcess([], 0, sample, '')):
            self.assertEqual(mod.pending_deletion_ids(Path('/media/usb')), {21336, 21337})
        for malformed in ('garbage\n', 'ID 21336 path @data\n',
                          'ID 21336 gen 1 top level 5 path @data\n',
                          'ID 21336 gen 1 top level 0 path DELETED\n'
                          'ID 21336 gen 1 top level 0 path DELETED\n'):
            with self.subTest(malformed=malformed), \
                 patch.object(mod, 'command', return_value=CompletedProcess([], 0, malformed, '')):
                with self.assertRaises(mod.Refused):
                    mod.pending_deletion_ids(Path('/media/usb'))

    def test_native_busy_error_classification(self):
        actual = 'ERROR: cannot delete qgroup 0/21336: Device or resource busy\n'
        self.assertTrue(mod.expected_busy_errors(actual, {21336}))
        self.assertFalse(mod.expected_busy_errors(actual, set()))
        self.assertFalse(mod.expected_busy_errors('', {21336}))
        self.assertFalse(mod.expected_busy_errors(actual + 'ERROR: read-only filesystem\n', {21336}))
        self.assertFalse(mod.expected_busy_errors('ERROR: cannot delete qgroup 0/21336: Operation not permitted', {21336}))


class ContractTests(unittest.TestCase):
    def config(self, mode, **extra):
        base = {'snapshot_root':'/media/usb/@snapshots' if mode == 'source' else '/@data/mars-received',
                'lock_path':'/run/lock/btrfs-snapshot-manager.lock',
                'writer_lock_path':'/media/usb/@data/backup/.btrfs-snapshot-writer.lock' if mode == 'source' else '/@data/mars-received/.replication-state/writer.lock'}
        if mode == 'receiver':
            base.update(mode='receiver', receiver_state_dir='/@data/mars-received/.replication-state')
        base.update(extra)
        return base

    def check(self, mode, data, fs=None):
        writer = data['writer_lock_path']
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            return mod.contract(Path('/etc/btrfs-snapshot-manager.json'),
                                Path(fs or ('/media/usb' if mode == 'source' else '/')),
                                mode, Path(writer))

    def test_host_specific_configuration(self):
        for mode in ('source', 'receiver'):
            with self.subTest(mode=mode):
                data = {
                    'schema': 1, 'mode': mode,
                    'filesystem': '/media/usb' if mode == 'source' else '/',
                    'snapshot_manager_config': '/etc/btrfs-snapshot-manager.json',
                    'expected_writer_lock': self.config(mode)['writer_lock_path'],
                    'max_stale': 2000,
                }
                with patch.object(Path, 'read_text', return_value=json.dumps(data)):
                    settings = mod.load_maintenance_config(mod.MAINTENANCE_CONFIG)
                self.assertEqual(settings['mode'], mode)
                self.assertEqual(settings['fs'], Path(data['filesystem']))
                self.assertEqual(settings['expected_writer'], Path(data['expected_writer_lock']))

    def test_invalid_host_specific_configuration(self):
        valid = {
            'schema': 1, 'mode': 'source', 'filesystem': '/media/usb',
            'snapshot_manager_config': '/etc/btrfs-snapshot-manager.json',
            'expected_writer_lock': '/media/usb/@data/backup/.btrfs-snapshot-writer.lock',
            'max_stale': 2000,
        }
        changes = [
            {'mode': 'receiver'}, {'filesystem': '/'}, {'max_stale': 2001},
            {'max_stale': True}, {'schema': 2},
            {'snapshot_manager_config': '/tmp/fake.json'},
            {'expected_writer_lock': '../relative'},
            {'unrecognised': 'bad'},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(mod.Refused):
                with patch.object(Path, 'read_text', return_value=json.dumps({**valid, **change})):
                    mod.load_maintenance_config(mod.MAINTENANCE_CONFIG)
        with self.assertRaises(mod.Refused):
            mod.load_maintenance_config(Path('/tmp/wrong.json'))

    def test_valid_source_and_receiver(self):
        for mode in ('source', 'receiver'):
            with self.subTest(mode=mode):
                self.assertEqual(self.check(mode, self.config(mode)),
                                 Path(self.config(mode)['writer_lock_path']))

    def test_wrong_config_fail_closed(self):
        for mode, extra in [('source', {'writer_lock_path':'/run/fake.lock'}),
                            ('source', {'lock_path':'/tmp/other.lock'}),
                            ('source', {'snapshot_root':'/tmp'}),
                            ('receiver', {'receiver_state_dir':'/tmp'}),
                            ('receiver', {'mode':'source'})]:
            with self.subTest(mode=mode, extra=extra), self.assertRaises(mod.Refused):
                self.check(mode, {**self.config(mode), **extra})
        with self.assertRaises(mod.Refused):
            mod.absolute_path('/media/usb/../elsewhere', 'test')

    def test_lock_inode_and_contention(self):
        with tempfile.TemporaryDirectory() as name:
            lock = Path(name) / 'manager'
            with mod.lock_file(lock, create=True):
                self.assertTrue(lock.is_file())
                with self.assertRaises(BlockingIOError):
                    mod.lock_file(lock)
            with mod.lock_file(lock):
                pass
            symlink = Path(name) / 'link'
            symlink.symlink_to(lock)
            with self.assertRaises(OSError):
                mod.lock_file(symlink)
            hardlink = Path(name) / 'hardlink'
            os.link(lock, hardlink)
            with self.assertRaises(mod.Refused):
                mod.lock_file(lock)
            with self.assertRaises(FileNotFoundError):
                mod.lock_file(Path(name) / 'missing')


class RunTests(unittest.TestCase):
    def drive(self, *, execute, rows=None, live=None, supported=True, max_stale=2000,
              after=None, pending=None, pending_after=None, native_rc=0, native_stderr=''):
        before = rows if rows is not None else {'0/5':'<toplevel>', '0/256':'@data',
                                                  '0/257':'<stale>', '0/258':'<under deletion>'}
        after = after if after is not None else {k:v for k,v in before.items() if v!='<stale>'}
        pending = set() if pending is None else set(pending)
        pending_after = pending if pending_after is None else set(pending_after)
        with patch.object(mod.os, 'geteuid', return_value=0), \
             patch.object(mod, 'contract', return_value=Path('/fake-writer.lock')), \
             patch.object(mod, 'lock_file', return_value=contextlib.nullcontext()), \
             patch.object(mod, 'verify_mount', return_value='fake-uuid'), \
             patch.object(mod, 'qgroups', side_effect=[before, after]), \
             patch.object(mod, 'subvolume_ids', return_value={256} if live is None else live), \
             patch.object(mod, 'pending_deletion_ids', side_effect=[pending, pending_after]), \
             patch.object(mod, 'has_native_clear_stale', return_value=supported), \
             patch.object(mod, 'command', return_value=CompletedProcess([], native_rc, '', native_stderr)) as exec_command, \
             contextlib.redirect_stdout(io.StringIO()) as out:
            error = None
            try:
                mod.run(execute=execute, config_path=Path('/etc/btrfs-snapshot-manager.json'),
                        fs=Path('/media/usb'), mode='source',
                        expected_writer=Path('/fake-writer.lock'), max_stale=max_stale)
            except mod.Refused as exc:
                error = str(exc)
            return error, exec_command.call_args_list, out.getvalue()

    def test_dry_run_never_calls_mutating_tool(self):
        error, calls, output = self.drive(execute=False, pending={257})
        self.assertIsNone(error)
        self.assertFalse(calls)
        self.assertIn('dry_run=true', output)
        self.assertIn('stale_pending=1', output)

    def test_native_cleanup_one_call(self):
        error, calls, output = self.drive(execute=True)
        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, ('btrfs', 'qgroup', 'clear-stale', '/media/usb'))
        self.assertEqual(calls[0].kwargs, {'check': False})
        self.assertIn('removed=1', output)
        self.assertIn('result=complete', output)

    def test_partial_busy_is_expected_only_when_pending(self):
        before = {'0/5':'<toplevel>', '0/256':'@data',
                  '0/21336':'<stale>', '0/21501':'<stale>', '0/21502':'<stale>'}
        after = {'0/5':'<toplevel>', '0/256':'@data', '0/21336':'<stale>'}
        error, calls, output = self.drive(execute=True, rows=before, after=after,
                                         pending={21336}, native_rc=1,
                                         native_stderr='ERROR: cannot delete qgroup 0/21336: Device or resource busy\n')
        self.assertIsNone(error)
        self.assertEqual(len(calls), 1)
        self.assertIn('removed=2', output)
        self.assertIn('stale_after=1', output)
        self.assertIn('deferred_pending=1', output)
        self.assertIn('native_rc=1', output)
        self.assertIn('result=deferred_pending', output)

    def test_real_eleven_pending_ninety_one_eligible_case(self):
        before = {'0/5':'<toplevel>', '0/256':'@data'}
        before.update({f'0/{i}':'<stale>' for i in range(21600, 21702)})
        pending = set(range(21600, 21611))
        after = {'0/5':'<toplevel>', '0/256':'@data'}
        after.update({f'0/{i}':'<stale>' for i in pending})
        errors = ''.join(f'ERROR: cannot delete qgroup 0/{i}: Device or resource busy\n'
                         for i in sorted(pending))
        error, calls, output = self.drive(execute=True, rows=before, after=after,
                                         pending=pending, native_rc=1, native_stderr=errors)
        self.assertIsNone(error)
        self.assertIn('stale_before=102', output)
        self.assertIn('stale_eligible=91', output)
        self.assertIn('removed=91', output)
        self.assertIn('deferred_pending=11', output)

    def test_partial_failure_remains_failure_for_unexpected_error(self):
        before = {'0/5':'<toplevel>', '0/256':'@data', '0/21336':'<stale>', '0/21501':'<stale>'}
        after = {'0/5':'<toplevel>', '0/256':'@data', '0/21336':'<stale>'}
        for stderr in ('ERROR: I/O error\n',
                       'ERROR: cannot delete qgroup 0/21501: Device or resource busy\n',
                       'ERROR: cannot delete qgroup 0/21336: Device or resource busy\n'
                       'ERROR: permission denied\n'):
            with self.subTest(stderr=stderr):
                error, calls, output = self.drive(execute=True, rows=before, after=after,
                                                 pending={21336}, native_rc=1,
                                                 native_stderr=stderr)
                self.assertIn('native clear-stale failed', error)
                self.assertEqual(len(calls), 1)

    def test_deferred_requires_post_cleanup_pending_match(self):
        before = {'0/5':'<toplevel>', '0/256':'@data', '0/21336':'<stale>'}
        for pending, pending_after in [(set(), set()), ({21336}, set())]:
            with self.subTest(pending=pending, pending_after=pending_after):
                error, calls, output = self.drive(execute=True, rows=before,
                                                 after=before, pending=pending,
                                                 pending_after=pending_after)
                self.assertIn('without pending deletion', error)

    def test_fail_closed_on_unsupported_version_or_orphans(self):
        error, calls, output = self.drive(execute=True, supported=False)
        self.assertIn('lacks native', error)
        self.assertFalse(calls)
        error, calls, output = self.drive(execute=True, rows={'0/5':'<toplevel>', '0/259':'???'})
        self.assertIn('unmarked orphan', error)
        self.assertFalse(calls)
        error, calls, output = self.drive(execute=True, live={256, 257})
        self.assertIn('conflicts with live subvolume', error)
        self.assertFalse(calls)

    def test_bound_and_persisting_stale(self):
        error, calls, output = self.drive(execute=True, max_stale=1,
                                         rows={'0/5':'<toplevel>', '0/259':'<stale>', '0/260':'<stale>'})
        self.assertIn('exceed guarded', error)
        self.assertFalse(calls)
        error, calls, output = self.drive(execute=True,
                                         after={'0/5':'<toplevel>', '0/256':'@data',
                                                '0/257':'<stale>', '0/258':'<under deletion>'})
        self.assertIn('without pending deletion', error)
        self.assertEqual(len(calls), 1)

    def test_nonstale_mutation_detected(self):
        error, calls, output = self.drive(execute=True,
                                         after={'0/5':'<toplevel>', '0/256':'changed',
                                                '0/258':'<under deletion>'})
        self.assertIn('non-stale', error)


class IntegrationSourceTests(unittest.TestCase):
    def test_native_route_and_default_off(self):
        default = (PLAYBOOKS / 'roles/btrfs-replication/defaults/main.yaml').read_text()
        self.assertIn('btrfs_stale_qgroup_maintenance_install_enabled: false', default)
        self.assertIn('btrfs_stale_qgroup_maintenance_enabled: false', default)
        native = (PLAYBOOKS / 'roles/btrfs-replication/tasks/native.yaml').read_text()
        self.assertIn('import_tasks: qgroup-maintenance.yaml', native)
        tasks = (PLAYBOOKS / 'roles/btrfs-replication/tasks/qgroup-maintenance.yaml').read_text()
        self.assertIn("inventory_hostname in ['mars', 'backup']", tasks)
        self.assertIn('btrfs_stale_qgroup_maintenance_enabled is boolean', tasks)
        self.assertIn('not ansible_check_mode', tasks)
        self.assertIn('roles/snapshots/files/btrfs-clear-stale-qgroups.py', tasks)
        self.assertIn('btrfs-stale-qgroups.json.j2', tasks)
        self.assertIn('dest: /etc/btrfs-stale-qgroups.json', tasks)
        service = (ROOT / 'templates/btrfs-clear-stale-qgroups.service.j2').read_text()
        self.assertIn('--config /etc/btrfs-stale-qgroups.json --execute', service)
        self.assertNotIn('--mode', service)
        snapshots_tasks = (ROOT / 'tasks/main.yaml').read_text()
        self.assertNotIn('receiver stale-qgroup', snapshots_tasks)
        self.assertNotIn('inventory_hostname == \'backup\'', snapshots_tasks)


if __name__ == '__main__':
    unittest.main(verbosity=2)
