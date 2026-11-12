#!/usr/bin/env python3
"""0040 Step 12: receipt-independent receiver retention and fail-closed deletion."""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase, main, mock
import json
import shutil
import stat

SOURCE = Path(__file__).resolve().parents[1]/'files'/'btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('btrfs_shared_manager_test', SOURCE)
m = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = m
spec.loader.exec_module(m)

STAMPS = ['20261001-000000Z', '20261002-000000Z', '20261003-000000Z',
          '20261004-000000Z', '20261005-000000Z', '20261006-000000Z']
UUIDS = {stamp: f'77777777-2222-3333-4444-{i:012x}' for i,stamp in enumerate(STAMPS, 1)}
POLICY = m.RetentionPolicy(hourly=0, daily=0, weekly=0, monthly=0, yearly=0,
                           minimum_age_minutes=30)
NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)

class Cases(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)/'received'
        self.rec = self.root/'@data'
        self.state = self.root/'.replication-state'
        self.rec.mkdir(parents=True); self.state.mkdir()
        for stamp in STAMPS:
            (self.rec/stamp).mkdir()
        self.parent = STAMPS[-2]
        self.prior = STAMPS[-3]
        self.state_record = {'schema':1, 'parent':{'timestamp':self.parent,'uuid':UUIDS[self.parent]},
                             'prior':{'timestamp':self.prior,'uuid':UUIDS[self.prior]}}
        (self.state/'.simple-agreed-parent.json').write_text(json.dumps(self.state_record))
        self.holds = {}
        self.readonly = True
        self.deleted = []
        self.fail_delete = False
        self.config = SimpleNamespace(mode='receiver', snapshot_root=self.root,
            receiver_state_dir=self.state, lock_path=Path('/run/lock/btrfs-snapshot-manager.lock'),
            sources=(m.SnapshotSource('@data', None, snapshot_directory=self.rec),),
            retention=POLICY, checkpoint_holds_required=True, receiver_prune_enabled=False)
        self.patches = [
            mock.patch.object(m, '_SIMPLE_RECEIVER_ROOT', self.root),
            mock.patch.object(m, '_SIMPLE_RECEIVED', self.rec),
            mock.patch.object(m, '_SIMPLE_STATE', self.state),
            mock.patch.object(m, '_SIMPLE_RECEIVER_MOUNT', self.root),
            mock.patch.object(m, 'preflight', lambda c: None),
            mock.patch.object(m, 'simplified_agreed_parent_pins', lambda c: {self.parent, self.prior}),
            mock.patch.object(m, 'agreed_parent_pins', lambda c: set()),
            mock.patch.object(m, 'read_checkpoint_holds', lambda c: self.holds),
            mock.patch.object(m, 'run', self.fake_run),
            mock.patch.object(m, 'validate_prune_candidate', self.check_prune_candidate),
        ]
        for patch in self.patches:
            patch.start(); self.addCleanup(patch.stop)

    def check_prune_candidate(self, conf, source, stamp):
        assert (self.rec/stamp).is_dir() and not (self.rec/stamp).is_symlink()

    def fake_run(self, cmd, **kwargs):
        from subprocess import CompletedProcess
        if cmd[:3] == ['btrfs','filesystem','show']:
            return CompletedProcess(cmd,0,'uuid: b915f967-7cb4-4c14-b11b-f52209637a22\n','')
        if cmd[:3] == ['btrfs','subvolume','show']:
            path = Path(cmd[-1]); stamp = path.name
            if not path.is_dir(): raise m.SnapshotError('missing snapshot')
            return CompletedProcess(cmd,0,f'UUID: 88888888-2222-3333-4444-000000000001\nReceived UUID: {UUIDS[stamp]}\nSubvolume ID: {STAMPS.index(stamp)+250}\n','')
        if cmd[:4] == ['btrfs','property','get','-ts']:
            return CompletedProcess(cmd,0,'ro=true\n' if self.readonly else 'ro=false\n','')
        if cmd[:3] == ['btrfs','subvolume','delete']:
            if self.fail_delete: raise m.SnapshotError('simulated interruption')
            self.deleted.append(Path(cmd[-1]).name)
            shutil.rmtree(cmd[-1]); return CompletedProcess(cmd,0,'','')
        raise AssertionError(f'unexpected command: {cmd}')

    def plan(self):
        return m.receiver_simple_plan(self.config, now=NOW)

    def test_plan_pins_current_prior_and_receiver_ahead(self):
        plan=self.plan()
        self.assertIn(self.parent,plan['keep'])
        self.assertIn(self.prior,plan['keep'])
        self.assertIn(STAMPS[-1],plan['keep'])
        self.assertEqual(plan['candidates'], STAMPS[2::-1])

    def test_legacy_receipt_preserved_but_not_a_retention_pin(self):
        receipt=self.state/(STAMPS[0]+'.json')
        receipt.write_text('{"source_filesystem_uuid":"WRONG"}')
        old_bytes=receipt.read_bytes()
        plan=self.plan()
        self.assertNotIn(STAMPS[0],plan['keep'])
        self.assertIn(STAMPS[0],plan['candidates'])
        self.assertIn(STAMPS[0],plan['historical_receipts_on_candidates'])
        self.assertEqual(plan['historical_receipts_orphaned'],[])
        self.assertEqual(receipt.read_bytes(),old_bytes)
        # The read-only plan explicitly reports evidence even when eligible.
        from io import StringIO
        from contextlib import redirect_stdout
        output=StringIO()
        with redirect_stdout(output):
            m.receiver_simple_print_plan(plan)
        self.assertIn('"historical_receipts_on_candidates": 1',output.getvalue())
        self.assertIn('historical_receipt=preserved',output.getvalue())

    def test_held_snapshot_bound_to_received_uuid(self):
        stamp=STAMPS[1]
        self.holds[stamp]={'reason':'historical', 'source_uuids':{'@data':UUIDS[stamp]}}
        self.assertIn(stamp,self.plan()['keep'])
        self.holds[stamp]['source_uuids']['@data']=UUIDS[STAMPS[0]]
        with self.assertRaisesRegex(m.SnapshotError,'hold identity mismatch'):
            self.plan()

    def test_orphan_receipt_preserved_and_not_used_as_identity_proof(self):
        receipt=self.state/'20260901-000000Z.json'
        receipt.write_text('{"untrusted":"evidence"}')
        original=receipt.read_bytes()
        plan=self.plan()
        self.assertIn('20260901-000000Z',plan['historical_receipts_orphaned'])
        self.assertNotIn('20260901-000000Z',plan['keep'])
        self.assertEqual(receipt.read_bytes(),original)

    def test_orphan_receipt_symlink_refuses(self):
        (self.state/'20260901-000000Z.json').symlink_to(self.state/'.simple-agreed-parent.json')
        with self.assertRaisesRegex(m.SnapshotError,'unsafe historical receipt'):
            self.plan()

    def test_symlink_timestamp_blocks_plan(self):
        (self.rec/'20261007-000000Z').symlink_to(self.rec/STAMPS[-1])
        with self.assertRaisesRegex(m.SnapshotError,'unexpected received snapshot entry'):
            self.plan()

    def test_writable_candidate_blocks_plan(self):
        self.readonly=False
        with self.assertRaisesRegex(m.SnapshotError,'writable received snapshot'):
            self.plan()

    def test_duplicate_received_uuid_blocks_plan(self):
        UUIDS[STAMPS[0]]=UUIDS[STAMPS[1]]
        self.addCleanup(UUIDS.__setitem__, STAMPS[0], '77777777-2222-3333-4444-000000000001')
        with self.assertRaisesRegex(m.SnapshotError,'duplicate received UUID'):
            self.plan()

    def test_parent_received_uuid_mismatch_blocks_plan(self):
        self.state_record['parent']['uuid']=UUIDS[STAMPS[0]]
        (self.state/'.simple-agreed-parent.json').write_text(json.dumps(self.state_record))
        with self.assertRaisesRegex(m.SnapshotError,'parent Btrfs identity mismatch'):
            self.plan()

    def test_missing_parent_blocks_plan(self):
        shutil.rmtree(self.rec/self.parent)
        with self.assertRaisesRegex(m.SnapshotError,'parent Btrfs identity mismatch'):
            self.plan()

    def test_pending_transfer_or_prune_blocks_plan(self):
        for name in m._SIMPLE_BLOCKERS:
            path=self.state/name;path.write_text('pending')
            with self.assertRaisesRegex(m.SnapshotError,'unfinished transaction'):
                self.plan()
            path.unlink()

    def test_wrong_root_or_lock_blocks_plan(self):
        self.config.lock_path=Path('/tmp/other-lock')
        with self.assertRaisesRegex(m.SnapshotError,'unexpected simplified receiver configuration'):
            self.plan()

    def test_disabled_prune_has_zero_mutation(self):
        with self.assertRaisesRegex(m.SnapshotError,'disabled'):
            m.receiver_simple_prune(self.config,max_delete=2)
        self.assertFalse(self.deleted)

    def test_prune_includes_receipted_candidates_preserving_receipt_bytes(self):
        stamp=STAMPS[0]
        receipt=self.state/(stamp+'.json')
        receipt.write_text('historical receipt bytes: preserved\n')
        original=receipt.read_bytes()
        self.config.receiver_prune_enabled=True
        m.receiver_simple_prune(self.config,max_delete=3)
        self.assertEqual(self.deleted,STAMPS[2::-1])
        self.assertFalse((self.rec/stamp).exists())
        self.assertEqual(receipt.read_bytes(),original)
        self.assertTrue((self.rec/self.parent).exists())
        self.assertTrue((self.rec/self.prior).exists())
        self.assertFalse((self.state/'.simple-prune-pending.json').exists())
        plan=self.plan()
        self.assertIn(stamp,plan['historical_receipts_orphaned'])
        self.assertEqual(plan['candidates'],[])
        self.assertEqual(m.receiver_simple_prune(self.config,max_delete=3),0)

    def test_checkpoint_hold_protects_snapshot_even_with_legacy_receipt(self):
        stamp=STAMPS[0]
        self.holds[stamp]={'reason':'explicit hold','source_uuids':{'@data':UUIDS[stamp]}}
        receipt=self.state/(stamp+'.json');receipt.write_text('older receipt')
        self.config.receiver_prune_enabled=True
        m.receiver_simple_prune(self.config,max_delete=3)
        self.assertNotIn(stamp,self.deleted)
        self.assertTrue((self.rec/stamp).exists())
        self.assertEqual(receipt.read_text(),'older receipt')

    def test_interrupted_delete_persists_journal_and_blocks_retry(self):
        self.config.receiver_prune_enabled=True
        self.fail_delete=True
        with self.assertRaisesRegex(m.SnapshotError,'simulated interruption'):
            m.receiver_simple_prune(self.config,max_delete=1)
        journal=self.state/'.simple-prune-pending.json'
        self.assertTrue(journal.is_file())
        self.assertEqual(stat.S_IMODE(journal.stat().st_mode),0o600)
        self.fail_delete=False
        with self.assertRaisesRegex(m.SnapshotError,'unfinished transaction'):
            m.receiver_simple_prune(self.config,max_delete=1)
        self.assertEqual(self.deleted,[])

    def test_invalid_max_delete_blocks_mutation(self):
        self.config.receiver_prune_enabled=True
        for n in (0,21,-1):
            with self.assertRaisesRegex(m.SnapshotError,'max-delete'):
                m.receiver_simple_prune(self.config,max_delete=n)
        self.assertFalse(self.deleted)

if __name__=='__main__': main()
