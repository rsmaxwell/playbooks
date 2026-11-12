#!/usr/bin/env python3
"""0040 Step 5: non-destructive migration/prune adversarial regression.
All temporary directories are disposable; no Btrfs deletion is performed.
"""
import importlib.util
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

manager = Path(__file__).resolve().parents[1] / 'files/btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('step05_manager', manager)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def rejected(action, reason):
    try:
        action()
    except m.SnapshotError:
        print('PASS:', reason)
    else:
        raise AssertionError('FAIL: ' + reason)


with tempfile.TemporaryDirectory(prefix='0040-step05-') as temp:
    root = Path(temp)
    for name in ('root', '@data'):
        (root / name).mkdir()
    payload = {
        'snapshot_root': str(root),
        'sources': [{'name': name, 'path': str(root / name), 'required': name=='@data', 'creation': name=='@data', 'prune': name=='@data'} for name in ('root', '@data')],
        'retention': {'hourly': 1, 'daily': 1, 'weekly': 1, 'monthly': 1, 'yearly': 1,
                      'minimum_age_minutes': 30},
    }
    path = root / 'config.json'
    path.write_text(json.dumps(payload))
    config = m.load_config(path)
    older, newer = '20261001-080000Z', '20261002-080000Z'
    (root / '@data' / older).mkdir()
    (root / '@data' / newer).mkdir()
    (root / 'root' / older).mkdir()
    complete, incomplete = m.managed_snapshot_sets(config)
    assert len(complete) == 2 and not incomplete
    print('PASS: mixed paired and @data-only histories are complete')

    # Even in a dry run, no deletion operation may be dispatched.
    with patch.object(m, 'preflight'), patch.object(m, 'retention_keep_set', return_value=set()), \
         patch.object(m, 'replication_pins', return_value={older}), \
         patch.object(m, 'read_checkpoint_holds', return_value={}), \
         patch.object(m, 'validate_prune_candidate'), patch.object(m, 'run') as execute:
        output = io.StringIO()
        with redirect_stdout(output):
            m.prune(config, dry_run=True)
        assert older not in [line.split()[2] for line in output.getvalue().splitlines()
                             if line.startswith('WOULD-DELETE')]
        assert f'WOULD-DELETE @data {newer}' in output.getvalue()
        assert f'WOULD-DELETE root {newer}' not in output.getvalue()
        execute.assert_not_called()
    print('PASS: source pin protects paired snapshot; dry-run only plans existing @data candidate and never mutates')

    with patch.object(m, 'preflight'), patch.object(m, 'retention_keep_set', return_value=set()), \
         patch.object(m, 'replication_pins', return_value=set()), \
         patch.object(m, 'read_checkpoint_holds', return_value={newer: {'reason': 'hold'}}), \
         patch.object(m, 'validate_prune_candidate'), patch.object(m, 'run') as execute:
        output = io.StringIO()
        with redirect_stdout(output):
            m.prune(config, dry_run=True)
        assert f'WOULD-DELETE @data {newer}' not in output.getvalue()
        execute.assert_not_called()
    print('PASS: hold survives removal of mandatory root requirement')

    (root / 'root' / '20261003-080000Z').mkdir()
    with patch.object(m, 'preflight'), patch.object(m, 'run') as execute:
        rejected(lambda: m.prune(config, dry_run=True), 'root-only incomplete set prevents all pruning')
        execute.assert_not_called()
    (root / 'root' / '20261003-080000Z').rmdir()

    # A disappearing candidate must block the transaction before deletion.
    with patch.object(m, 'preflight'), patch.object(m, 'retention_keep_set', return_value=set()), \
         patch.object(m, 'replication_pins', return_value=set()), \
         patch.object(m, 'read_checkpoint_holds', return_value={}), \
         patch.object(m, 'validate_prune_candidate', side_effect=m.SnapshotError('disappeared')), \
         patch.object(m, 'run') as execute:
        rejected(lambda: m.prune(config, dry_run=False), 'disappearing candidate fails before deletion')
        execute.assert_not_called()

    payload['sources']=[{'name': name, 'path': str(root/name)} for name in ('root','@data')]
    for val in (['@data', '@data'], ['unrecognised'], []):
        payload['required_snapshot_sources'] = val
        path.write_text(json.dumps(payload))
        rejected(lambda: m.load_config(path), 'invalid source contract rejected: ' + repr(val))

    payload['required_snapshot_sources'] = ['@data']
    payload['creation_source_names'] = ['root']
    path.write_text(json.dumps(payload))
    rejected(lambda: m.load_config(path), 'creation excludes required source')
    payload['creation_source_names'] = ['@data']
    path.write_text(json.dumps(payload))
    receiver = dict(payload, mode='receiver', receiver_state_dir=str(root),
                    sources=[{'name': '@data', 'snapshot_directory': str(root/'@data')}])
    path.write_text(json.dumps(receiver))
    receiver_config = m.load_config(path)
    rejected(lambda: m.prune(receiver_config, dry_run=False), 'receiver ordinary prune remains unavailable')

print('PASS: Step 5 focused source migration adversarial tests (non-destructive)')
