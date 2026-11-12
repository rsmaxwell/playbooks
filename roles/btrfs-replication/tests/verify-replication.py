#!/usr/bin/env python3
"""Compact simplified 0040 source-level regression; no snapshots are modified."""
import importlib.machinery
import os
import importlib.util
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'files' / 'btrfs-simplified-replication.py'
loader = importlib.machinery.SourceFileLoader('simplified0040', str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
U1 = '11111111-1111-1111-1111-111111111111'
U2 = '22222222-2222-2222-2222-222222222222'
U3 = '33333333-3333-3333-3333-333333333333'
A = '20261030-170009Z'
B = '20261101-140039Z'
C = '20261102-140039Z'

def info(uuid=U2, received='-', flags='-'):
    return {'UUID': uuid, 'Received UUID': received, 'Flags': flags, 'Parent UUID': U1}

class Cases(unittest.TestCase):
    def setUp(self):
        self.state = m.initial_state(A, U1)
        # Source-cycle tests must never touch the actual host manager lock.
        lock_dir = tempfile.TemporaryDirectory()
        self.addCleanup(lock_dir.cleanup)
        lock_patch = patch.object(m, 'MANAGER_LOCK', Path(lock_dir.name) / 'manager.lock')
        lock_patch.start()
        self.addCleanup(lock_patch.stop)

    def fixture_root_owned(self, path):
        """Simulate only the ownership of one disposable test-state file.

        Production load_state() must continue to require uid 0. Ordinary
        users cannot chown temporary fixtures, so patch just the uid field
        returned by Path.stat for the chosen test file. Mode, link count,
        size and all other paths retain real filesystem values.
        """
        real_stat = Path.stat

        def fixture_stat(candidate, *args, **kwargs):
            result = real_stat(candidate, *args, **kwargs)
            if candidate == path:
                fields = list(result)
                fields[4] = 0  # os.stat_result index for st_uid
                return os.stat_result(fields)
            return result

        owner_patch = patch.object(Path, 'stat', fixture_stat)
        owner_patch.start()
        self.addCleanup(owner_patch.stop)

    def test_sender_status_uses_verified_readonly_identity_without_mutation(self):
        from contextlib import nullcontext
        from io import StringIO
        from contextlib import redirect_stdout
        new = m.advance(self.state, B, U2)
        calls=[]
        def peer(*args):
            calls.append(args)
            if args == ('status',):
                return {'state': self.state}
            if args == ('status', '--snapshot', A):
                return {'state': self.state, 'candidate': info(uuid=U2, received=U1, flags='readonly')}
            raise AssertionError(args)
        def inspect(_root, stamp):
            return info(uuid=U1 if stamp == A else U2, flags='readonly')
        def select(stamp):
            self.assertEqual(stamp, A)
            return (B, U2)
        with patch.object(m, 'require_filesystem'), patch.object(m, 'safe_directory'), \
             patch.object(m, 'locked', return_value=nullcontext()), \
             patch.object(m, 'load_state', return_value=self.state), \
             patch.object(m, 'subvolume_info', side_effect=inspect), \
             patch.object(m, 'peer', side_effect=peer), \
             patch.object(m, 'choose_next', side_effect=select), \
             patch.object(m, 'save_state') as save, \
             patch.object(m, 'stream_send') as send, \
             patch.object(m.os, 'geteuid', return_value=0):
            output = StringIO()
            with redirect_stdout(output):
                code = m.main(['sender', 'status'])
        import json
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['preflight']['action'], 'incremental')
        self.assertEqual(calls, [('status',), ('status', '--snapshot', A)])
        save.assert_not_called()
        send.assert_not_called()

    def test_sender_status_rejects_unverified_receiver_identity(self):
        with patch.object(m, 'load_state', return_value=self.state), \
             patch.object(m, 'subvolume_info', return_value=info(uuid=U1, flags='readonly')), \
             patch.object(m, 'peer', side_effect=[{'state': self.state},
                {'state': self.state, 'candidate': info(uuid=U2, received=U3, flags='readonly')}]), \
             patch.object(m, 'choose_next') as choose:
            with self.assertRaisesRegex(m.Refuse, 'Receiver parent identity'):
                m.sender_readonly_status()
            choose.assert_not_called()

    def test_sender_status_receiver_ahead_does_not_reconcile_or_save(self):
        advanced = m.advance(self.state, B, U2)
        def inspect(_root, stamp):
            return info(uuid=U1 if stamp == A else U2, flags='readonly')
        with patch.object(m, 'load_state', return_value=self.state), \
             patch.object(m, 'subvolume_info', side_effect=inspect), \
             patch.object(m, 'peer', side_effect=[{'state': advanced},
                {'state': advanced, 'candidate': info(uuid=U3, received=U2, flags='readonly')}]), \
             patch.object(m, 'choose_next') as choose, \
             patch.object(m, 'save_state') as save:
            result = m.sender_readonly_status()
        self.assertEqual(result['preflight']['action'], 'receiver-ahead-reconciliation-required')
        choose.assert_not_called()
        save.assert_not_called()

    def test_state_record_and_prior(self):
        result = m.advance(self.state, B, U2)
        self.assertEqual(result['prior'], {'timestamp': A, 'uuid': U1})
        self.assertEqual(m.protected_stamps(result), {A, B})

    def test_invalid_state_or_rollback_refuses(self):
        with self.assertRaises(m.Refuse): m.advance(self.state, A, U1)
        with self.assertRaises(m.Refuse): m.validate_state({'schema': 1, 'parent': self.state['parent']})
        with self.assertRaises(m.Refuse): m.initial_state('../escape', U1)

    def test_receiver_ahead_lost_ack(self):
        receiver = m.advance(self.state, B, U2)
        self.assertEqual(m.reconcile(self.state, receiver), 'receiver-ahead')
        self.assertEqual(m.reconcile(receiver, receiver), 'equal')

    def test_ambiguous_parent_divergence_refuses(self):
        b = m.advance(self.state, B, U2)
        c = m.advance(self.state, C, U3)
        with self.assertRaises(m.Refuse): m.reconcile(b, c)
        with self.assertRaises(m.Refuse): m.reconcile(b, self.state)

    def test_state_atomic_readback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.simple-agreed-parent.json'
            self.fixture_root_owned(path)
            m.save_state(path, self.state, create=True)
            self.assertEqual(m.load_state(path), self.state)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(m.Refuse): m.save_state(path, self.state, create=True)
            new = m.advance(self.state, B, U2)
            m.save_state(path, new)
            self.assertEqual(m.load_state(path), new)

    def test_state_rejects_nonroot_owner_and_insecure_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.simple-agreed-parent.json'
            m.save_state(path, self.state, create=True)
            real_stat = Path.stat

            def nonroot_stat(candidate, *args, **kwargs):
                result = real_stat(candidate, *args, **kwargs)
                if candidate == path:
                    fields = list(result)
                    fields[4] = 1001
                    return os.stat_result(fields)
                return result

            with patch.object(Path, 'stat', nonroot_stat):
                with self.assertRaisesRegex(m.Refuse, 'Unsafe state permissions/size'):
                    m.load_state(path)

            self.fixture_root_owned(path)
            path.chmod(0o640)
            with self.assertRaisesRegex(m.Refuse, 'Unsafe state permissions/size'):
                m.load_state(path)

    def test_single_nonblocking_manager_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manager.lock'
            fd = m.take_lock(path)
            try:
                with self.assertRaises(m.Deferred): m.take_lock(path)
            finally:
                import os
                os.close(fd)
            fd2 = m.take_lock(path)
            import os
            os.close(fd2)

    def test_readonly_lock_never_creates_missing_lockfile(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'missing-manager.lock'
            with self.assertRaises(FileNotFoundError):
                m.take_lock(path, create=False)
            self.assertFalse(path.exists())
            fd = m.take_lock(path)
            import os
            os.close(fd)
            fd = m.take_lock(path, create=False)
            os.close(fd)

    def test_receiver_backoff_uses_configured_lock(self):
        # Regression for a default-argument bug: take_lock(path=MANAGER_LOCK)
        # captured the production path at import time, so an isolated receiver
        # ignored its configured disposable lock and did not back off.
        import io
        import os
        from contextlib import redirect_stderr
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'fixture-manager.lock'
            with patch.object(m, 'MANAGER_LOCK', path), \
                 patch.object(m.os, 'geteuid', return_value=0):
                fd = m.take_lock(path)
                try:
                    errors = io.StringIO()
                    with redirect_stderr(errors):
                        result = m.main(['receiver', 'status'])
                    self.assertEqual(result, 75, errors.getvalue())
                    self.assertIn('lock busy', errors.getvalue())
                finally:
                    os.close(fd)

    def test_absent_or_complete_candidate_never_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m, 'legacy_blocks', return_value=False):
                self.assertEqual(m.classify_candidate(B, U2, self.state,
                                 inspect=lambda s: None, receipts_dir=Path(temp)), 'absent')
                self.assertEqual(m.classify_candidate(B, U2, self.state,
                                 inspect=lambda s: info(received=U2, flags='readonly'),
                                 receipts_dir=Path(temp)), 'complete')

    def test_incomplete_cleanup_exact_subvolume_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(m, 'legacy_blocks', return_value=False), \
                 patch.object(m, 'RECEIVER_STATE', root / '.simple-agreed-parent.json'):
                present={'value': info()}
                deleted=[]
                def inspect(_): return present['value']
                def delete(s):
                    deleted.append(s)
                    present['value'] = None
                self.assertTrue(m.remove_incomplete(B, U2, self.state,
                                inspect=inspect, delete=delete, readback=inspect))
                self.assertEqual(deleted, [B])
                with self.assertRaises(m.Refuse):
                    m.remove_incomplete(B, U2, self.state,
                                        inspect=inspect, delete=delete, readback=inspect)

    def test_readonly_or_received_unknown_candidate_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m, 'legacy_blocks', return_value=False):
                for obj in [info(flags='readonly'), info(received=U3), info(received=U3,flags='readonly')]:
                    with self.assertRaises(m.Refuse):
                        m.classify_candidate(B, U2, self.state,
                            inspect=lambda s: obj, receipts_dir=Path(temp))

    def test_held_or_legacy_receipt_refuses(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/(B+'.json')).write_text('legacy receipt')
            with patch.object(m, 'legacy_blocks', return_value=False):
                with self.assertRaises(m.Refuse):
                    m.classify_candidate(B,U2,self.state,inspect=lambda s:info(),receipts_dir=root)
                with self.assertRaises(m.Refuse):
                    m.classify_candidate(A,U1,self.state,inspect=lambda s:info(),receipts_dir=root)

    def test_choose_newest_eligible_newer(self):
        # Daily replication must catch up with hourly source creation in one cycle,
        # matching the retired --latest service rather than replaying each hour.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in (A,B,C): (root/name).mkdir()
            inspected=[]
            def inspect(stamp):
                inspected.append(stamp)
                return info(uuid=U3 if stamp == C else U2, flags='readonly')
            result=m.choose_next(A, source_root=root, inspect=inspect)
            self.assertEqual(result,(C,U3))
            self.assertEqual(inspected,[C])

    def test_latest_invalid_candidate_refuses_rather_than_falling_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in (A,B,C): (root/name).mkdir()
            with self.assertRaisesRegex(m.Refuse,'Unsafe source candidate: '+C):
                m.choose_next(A, source_root=root,
                    inspect=lambda s: info(uuid=U2, flags='-' if s == C else 'readonly'))

    def test_latest_selection_ignores_symlinks_and_non_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/A).mkdir(); (root/B).mkdir()
            (root/C).symlink_to(root/B, target_is_directory=True)
            (root/'20261103-140039Z').write_text('not a subvolume')
            self.assertEqual(m.choose_next(A, source_root=root,
                inspect=lambda s: info(uuid=U2, flags='readonly')), (B,U2))
            self.assertIsNone(m.choose_next(B, source_root=root,
                inspect=lambda s: info(uuid=U2, flags='readonly')))

    def test_invalid_candidate_prevents_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(m, 'legacy_blocks', return_value=False):
                seen=[]
                with self.assertRaises(m.Refuse):
                    m.remove_incomplete(B,U2,self.state,
                        inspect=lambda s:info(received=U2,flags='readonly'),
                        delete=lambda s: seen.append(s), readback=lambda s:None)
                self.assertEqual(seen,[])

    def test_receiver_incomplete_next_run_deletes_then_receives(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receiver = root / 'received'
            state_dir = root / 'state'
            receiver.mkdir(); state_dir.mkdir()
            state_file = state_dir / '.simple-agreed-parent.json'
            self.fixture_root_owned(state_file)
            m.save_state(state_file, self.state, create=True)
            candidate = {'value': info()}
            operations = []
            def inspect(_root, name):
                return (info(uuid=U1, received=U1, flags='readonly')
                        if name == A else candidate['value'])
            def run(*argv, timeout):
                operations.append(tuple(argv))
                if argv[1] == 'subvolume': candidate['value'] = None
                elif argv[1] == 'receive':
                    self.assertIsNone(candidate['value'])
                    candidate['value'] = info(uuid=U3, received=U2, flags='readonly')
            with patch.object(m, 'RECEIVER_STATE', state_file), \
                 patch.object(m, 'RECEIVED', receiver), \
                 patch.object(m, 'subvolume_info', side_effect=inspect), \
                 patch.object(m, 'legacy_blocks', return_value=False):
                result = m.receive_receiver(B, U2, A, U1, run=run)
            self.assertEqual(result['state'], m.advance(self.state,B,U2))
            self.assertEqual([command[1] for command in operations], ['subvolume','receive'])
            self.assertEqual(m.load_state(state_file)['parent']['timestamp'], B)

    def test_receiver_failure_does_not_advance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            receiver = root / 'received'
            receiver.mkdir()
            state_file = root / '.simple-agreed-parent.json'
            self.fixture_root_owned(state_file)
            m.save_state(state_file,self.state,create=True)
            def inspect(_root, name):
                return info(uuid=U1,received=U1,flags='readonly') if name == A else None
            with patch.object(m,'RECEIVER_STATE',state_file), \
                 patch.object(m,'RECEIVED',receiver), \
                 patch.object(m,'legacy_blocks',return_value=False), \
                 patch.object(m,'subvolume_info',side_effect=inspect):
                with self.assertRaises(m.Refuse):
                    m.receive_receiver(B,U2,A,U1,run=lambda *a,**kw: (_ for _ in ()).throw(m.Refuse('interrupted')))
            self.assertEqual(m.load_state(state_file),self.state)

    def test_sender_lost_ack_advances_local_without_retransmission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root/'source'; source.mkdir()
            state_file = root/'.simple-agreed-parent.json'
            self.fixture_root_owned(state_file)
            m.save_state(state_file,self.state,create=True)
            remote = m.advance(self.state,B,U2)
            args = SimpleNamespace(operation='cycle')
            def inspect(_root, name):
                return info(uuid=U1 if name==A else U2, received='-',flags='readonly')
            with patch.object(m,'SOURCE',source), \
                 patch.object(m,'SOURCE_STATE',state_file), \
                 patch.object(m,'require_filesystem',return_value=None), \
                 patch.object(m,'subvolume_info',side_effect=inspect), \
                 patch.object(m,'peer',return_value={'state':remote}), \
                 patch.object(m,'stream_send',side_effect=AssertionError('must not retransmit')):
                m.sender_main(args)
            self.assertEqual(m.load_state(state_file),remote)

    def test_completed_candidate_uses_advance_without_retransmit(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/'source'; source.mkdir()
            state_file=root/'.simple-agreed-parent.json'
            self.fixture_root_owned(state_file)
            m.save_state(state_file,self.state,create=True)
            remote=m.advance(self.state,B,U2)
            commands=[]
            def peer(operation,*args):
                commands.append(operation)
                if operation=='status' and not args:
                    return {'state':self.state}
                if operation=='status':
                    return {'state':remote if 'advance' in commands else self.state,
                            'candidate':info(received=U2,flags='readonly')}
                if operation=='advance': return {'state':remote}
                raise AssertionError(operation)
            def inspect(_root,name): return info(uuid=U1,flags='readonly')
            with patch.object(m,'SOURCE',source), \
                 patch.object(m,'SOURCE_STATE',state_file), \
                 patch.object(m,'require_filesystem',return_value=None), \
                 patch.object(m,'subvolume_info',side_effect=inspect), \
                 patch.object(m,'peer',side_effect=peer), \
                 patch.object(m,'choose_next',return_value=(B,U2)), \
                 patch.object(m,'stream_send',side_effect=AssertionError('must not retransmit')):
                m.sender_main(SimpleNamespace(operation='cycle'))
            self.assertEqual(commands,['status','status','advance','status'])
            self.assertEqual(m.load_state(state_file),remote)

    def test_filesystem_identity_refusal(self):
        with patch.object(m,'call',return_value=SimpleNamespace(stdout='Label: none uuid: '+U1+'\n')):
            m.require_filesystem(Path('/fixture'),U1)
            with self.assertRaises(m.Refuse): m.require_filesystem(Path('/fixture'),U2)

if __name__ == '__main__':
    unittest.main(verbosity=2)
