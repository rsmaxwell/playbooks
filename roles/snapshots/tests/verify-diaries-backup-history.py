#!/usr/bin/env python3
"""Source regression for deduplicated verified Diaries snapshot history."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

ROLE = Path(__file__).resolve().parents[1]
TOOL = ROLE / 'files' / 'diaries-backup-history.py'
spec = importlib.util.spec_from_file_location('diaries_backup_history', TOOL)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def make_occurrence(root: Path, stamp: str, backup_id: str, payload: str = 'a'):
    occurrence = root / '@data' / stamp
    parent = occurrence / 'backup' / 'pluto'
    generation = parent / '.diaries-backup-generations' / backup_id
    generation.mkdir(parents=True)
    manifest = {'schemaVersion': 2, 'backupId': backup_id, 'logicalDataset': 'production', 'testPayload': payload}
    manifest_path = generation / 'dataset-manifest.json'
    manifest_path.write_text(json.dumps(manifest, sort_keys=True))
    os.symlink(f'.diaries-backup-generations/{backup_id}', parent / 'diaries-backup')
    digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    marker = {
        'state': 'verified-published', 'snapshotEligible': True,
        'backupId': backup_id, 'logicalDataset': 'production',
        'datasetRelativePath': 'backup/pluto/diaries-backup', 'manifestSha256': digest,
    }
    (occurrence / 'backup' / '.diaries-snapshot-verified.json').write_text(json.dumps(marker))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / '@snapshots'
    (root / '@data').mkdir(parents=True)
    make_occurrence(root, '20261009-100000Z', '20261009-090000Z')
    make_occurrence(root, '20261009-110000Z', '20261009-090000Z')
    make_occurrence(root, '20261009-120000Z', '20261009-115000Z')
    cfg = module.HistoryConfig(root, '@data', 'backup/pluto/diaries-backup',
                               'backup/.diaries-snapshot-verified.json', Path('/fake/verifier'))
    occurrences, warnings = module.enumerate_occurrences(cfg)
    assert not warnings
    grouped = module.group_occurrences(occurrences)
    assert len(grouped[('production', '20261009-090000Z')]) == 2
    assert len(grouped) == 2
    assert not module.conflicted_groups(grouped)
    print('PASS: repeated Diaries backup IDs collapse to one history key with multiple snapshot occurrences')

    make_occurrence(root, '20261009-130000Z', '20261009-090000Z', payload='conflict')
    occurrences, warnings = module.enumerate_occurrences(cfg)
    grouped = module.group_occurrences(occurrences)
    assert ('production', '20261009-090000Z') in module.conflicted_groups(grouped)
    print('PASS: same logicalDataset/backupId with incompatible manifest identity is flagged as conflict')

    bad = root / '@data' / '20261009-140000Z'
    (bad / 'backup' / 'pluto').mkdir(parents=True)
    os.symlink('/tmp', bad / 'backup' / 'pluto' / 'diaries-backup')
    (bad / 'backup' / '.diaries-snapshot-verified.json').write_text(json.dumps({
        'state': 'verified-published', 'snapshotEligible': True,
        'backupId': '20261009-140000Z', 'logicalDataset': 'production',
        'datasetRelativePath': 'backup/pluto/diaries-backup', 'manifestSha256': '0' * 64,
    }))
    occurrences, warnings = module.enumerate_occurrences(cfg)
    assert any(stamp == '20261009-140000Z' and 'escapes snapshot occurrence' in message for stamp, message in warnings)
    print('PASS: history refuses dataset symlink escape outside the managed snapshot occurrence')

print('PASS: 0035 diaries-backup-history regression verified')

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    generations = base / '.diaries-backup-generations'
    generation = generations / '20261015-003023Z'
    generation.mkdir(parents=True)
    (generation / 'dataset-manifest.json').write_text(json.dumps({
        'schemaVersion': 2, 'backupId': '20261015-003023Z', 'logicalDataset': 'production'}))
    published = base / 'diaries-backup'
    published.symlink_to(generation.relative_to(base))
    occ = module.inspect_published(published)
    assert occ.snapshot == 'live' and occ.backup_id == '20261015-003023Z'
    assert occ.dataset_path == generation
    assert len(module.group_occurrences([occ])) == 1
    print('PASS: pluto resolves fixed publication without inventing Btrfs history')
    outside = base.parent / 'external'
    published.unlink()
    published.symlink_to(outside)
    try:
        module.inspect_published(published)
    except (module.HistoryError, OSError):
        pass
    else:
        raise AssertionError('external publication target accepted')
    published.unlink()
    published.symlink_to(generation.relative_to(base))
    (generation / 'dataset-manifest.json').write_text('{broken')
    try:
        module.inspect_published(published)
    except module.HistoryError:
        pass
    else:
        raise AssertionError('corrupt publication accepted')
    print('PASS: unsafe or corrupted live publication rejected')
