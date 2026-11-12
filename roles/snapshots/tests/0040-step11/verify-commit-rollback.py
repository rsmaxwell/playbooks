#!/usr/bin/env python3
"""Disposable, no-Btrfs adversarial tests for Step 11 transaction cores."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import json
import os
import tempfile

BASE = Path(__file__).resolve().parent

def load(name, filename):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(BASE / filename)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

m = load('step11commit', 'commit-checkpoint-hold-migration.py')
r = load('step11rollback', 'rollback-checkpoint-hold-migration.py')

def fixture(directory):
    root = Path(directory)
    holds = root / '.checkpoint-holds.json'
    document = {'schema': 1, 'holds': {}}
    uuids = {}
    for i, (stamp, reason) in enumerate(m.EXPECTED.items()):
        ids = {'root': f'0000000{i}-0000-0000-0000-000000000001', '@data': f'0000000{i}-0000-0000-0000-000000000002'}
        document['holds'][stamp] = {'reason': reason, 'source_uuids': ids}
        for source, uuid in ids.items():
            path = root / source / stamp
            path.mkdir(parents=True)
            uuids[path] = uuid
    holds.write_text(json.dumps(document, indent=2))
    holds.chmod(0o600)
    m.snapshot_uuid = lambda p: uuids[p]
    r.m.snapshot_uuid = lambda p: uuids[p]
    return root, holds

with tempfile.TemporaryDirectory() as d:
    root, holds = fixture(d)
    original = holds.read_bytes()
    backup, old, migrated = m.commit_transaction(holds, root)
    assert old == original and backup.read_bytes() == original
    assert holds.read_bytes() == migrated
    assert backup.stat().st_mode & 0o777 == 0o600
    assert {s for record in json.loads(migrated)['holds'].values() for s in record['source_uuids']} == {'@data'}
    print('PASS: atomic migration, durable backup, UUID/reason preservation')
    try:
        m.commit_transaction(holds, root)
    except m.UnsafeState:
        pass
    else:
        raise AssertionError('repeat accepted')
    assert holds.read_bytes() == migrated
    try:
        r.rollback_transaction(holds, root, backup)
    except Exception as e:
        raise AssertionError('rollback failed') from e
    assert holds.read_bytes() == original and backup.read_bytes() == original
    print('PASS: guarded rollback and repeated migration refusal')

with tempfile.TemporaryDirectory() as d:
    root, holds = fixture(d)
    backup = root / '.checkpoint-holds.0040-step11-before.json'
    backup.write_text('existing evidence')
    before = holds.read_bytes()
    try:
        m.commit_transaction(holds, root)
    except FileExistsError:
        pass
    else:
        raise AssertionError('collision accepted')
    assert backup.read_text() == 'existing evidence' and holds.read_bytes() == before
    print('PASS: backup collision leaves both files untouched')

with tempfile.TemporaryDirectory() as d:
    root, holds = fixture(d)
    before = holds.read_bytes()
    def change():
        holds.write_bytes(b'concurrent change')
    try:
        m.commit_transaction(holds, root, before_replace=change)
    except m.UnsafeState:
        pass
    else:
        raise AssertionError('concurrent modification accepted')
    assert holds.read_bytes() == b'concurrent change'
    assert (root / '.checkpoint-holds.0040-step11-before.json').read_bytes() == before
    print('PASS: source changed after validation refuses replacement')

with tempfile.TemporaryDirectory() as d:
    root, holds = fixture(d)
    before = holds.read_bytes()
    def fail(_p, _payload):
        raise OSError('injected replacement failure')
    try:
        m.commit_transaction(holds, root, replace=fail)
    except OSError:
        pass
    else:
        raise AssertionError('replacement failure ignored')
    assert holds.read_bytes() == before
    assert (root / '.checkpoint-holds.0040-step11-before.json').read_bytes() == before
    print('PASS: interrupted replacement retains original and rollback evidence')

with tempfile.TemporaryDirectory() as d:
    root, holds = fixture(d)
    backup, old, migrated = m.commit_transaction(holds, root)
    holds.write_bytes(b'tampered')
    try:
        r.rollback_transaction(holds, root, backup)
    except r.m.UnsafeState:
        pass
    else:
        raise AssertionError('rollback overwrote unexpected current file')
    assert holds.read_bytes() == b'tampered'
    print('PASS: rollback refuses unexpected hold contents')
print('PASS: 0040 Step 11 transaction regression (disposable fixture only)')
