#!/usr/bin/env python3
"""0035 Step 8 Gate B2: offline, disposable failure tests. Never connects to hosts."""
from __future__ import annotations
import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

receiver = load('gateb2_receiver', 'roles/btrfs-replication/files/btrfs-native-push-receiver.py')
manager = load('gateb2_manager', 'roles/snapshots/files/btrfs-snapshot-manager.py')
OLD = '20261012-100003Z'
NEW = '20261013-050016Z'
UUID = '7ad1f171-d1c7-0545-82a1-52e84adac979'
NEXT = '8bbb4807-9cea-4e42-a932-66e0254191c8'

def must_reject(fn, label):
    try: fn()
    except (RuntimeError, ValueError): print('PASS:', label)
    else: raise AssertionError(label + ' was accepted')

with tempfile.TemporaryDirectory(prefix='0035-gate-b2-') as td:
    base = Path(td)
    received, state = base/'received', base/'state'
    received.mkdir(); state.mkdir()
    with patch.object(receiver, 'ROOT', received), patch.object(receiver, 'STATE', state):
        assert receiver.validate(OLD, UUID, None, None, True, False)['action'] == 'full-baseline'
        print('PASS: empty disposable receiver accepts initial full baseline plan')
        existing = {'schema': 1, 'transport': 'btrfs-full', 'snapshot': OLD,
            'source_uuid': UUID, 'received_uuid': UUID, 'destination': str(received/OLD),
            'source_filesystem_uuid': receiver.SOURCE_FS,
            'receiver_filesystem_uuid': receiver.RECEIVER_FS,
            'read_only_verified': True, 'source_send_exit': 0, 'receiver_receive_exit': 0}
        (state/(OLD+'.json')).write_text(json.dumps(existing))
        with patch.object(receiver, 'inspect', return_value={'flags':'readonly', 'received_uuid':UUID}):
            assert receiver.receipt(OLD) is not None
            assert receiver.validate(NEW, NEXT, OLD, UUID, False, False)['action'] == 'incremental'
            print('PASS: valid receipted incremental parent is accepted')
            must_reject(lambda: receiver.validate(NEW,NEXT,OLD,NEXT,False,False), 'stale/mismatched parent UUID rejected')
            must_reject(lambda: receiver.validate(NEW,NEXT,None,None,True,False), 'implicit full reseed rejected')
            assert receiver.validate(NEW,NEXT,None,None,True,True)['action'] == 'full-baseline'
            print('PASS: explicit full reseed recognised')
        with patch.object(receiver, 'inspect', return_value={'flags':'readonly', 'received_uuid':'wrong'}):
            assert receiver.receipt(OLD) is None
            must_reject(lambda: receiver.validate(NEW,NEXT,OLD,UUID,False,False), 'corrupt accepted-parent received UUID rejected')
        with patch.object(receiver, 'inspect', return_value={'flags':'writable', 'received_uuid':UUID}):
            assert receiver.receipt(OLD) is None
            print('PASS: writable accepted-parent snapshot rejected')
        (received/NEW).mkdir()
        must_reject(lambda: receiver.validate(NEW,NEXT,None,None,True,True), 'duplicate/unaccepted destination rejected')
        (received/NEW).rmdir()
        receipt_new={'snapshot':NEW, 'source_uuid':NEXT}
        with patch.object(receiver.os, 'replace', side_effect=OSError('simulated ENOSPC')):
            try: receiver.atomic_receipt(receipt_new)
            except OSError: pass
            else: raise AssertionError('simulated receipt write failure unexpectedly succeeded')
        assert not (state/(NEW+'.json')).exists()
        assert json.loads((state/(OLD+'.json')).read_text()) == existing
        assert not list(state.glob('.push-receipt-*'))
        print('PASS: simulated disk-pressure publication failure leaves old receipt intact; no new accepted receipt')
        target=receiver.atomic_receipt(receipt_new)
        assert target.exists()
        must_reject(lambda: receiver.atomic_receipt(receipt_new), 'duplicate receipt publication rejected')
        print('PASS: atomic receipt recorded only after successful publication')

# Exercise real GFS policy only. Never invoke prune() or btrfs subvolume delete.
from datetime import datetime, timedelta, timezone
now=datetime(2026,10,15,12,tzinfo=timezone.utc)
policy=manager.RetentionPolicy(hourly=4,daily=3,weekly=2,monthly=2,yearly=2,minimum_age_minutes=30)
points=[(now-timedelta(hours=i)).strftime(manager.TIMESTAMP_FORMAT) for i in range(24*90)]
rows=[(name,manager.parse_timestamp(name),Path('/disposable-placeholder')/name) for name in points]
keep=manager.retention_keep_set(rows,policy,now)
assert points[0] in keep and len(keep)<len(rows)
assert points[1] in keep  # minimum age / recent protection
print('PASS: GFS policy protects newest and recent snapshots while thinning old entries')
print('GATE B2 offline contract tests PASS; kernel Btrfs/SSH/ENOSPC integration tests remain OPEN')
