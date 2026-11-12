#!/usr/bin/env python3
"""Non-destructive checkpoint-hold safety regression."""
from __future__ import annotations
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager

manager = Path(__file__).resolve().parents[1] / 'files' / 'btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('snapshot_hold_manager', manager)
import sys
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

# On mango this regression runs as richard. Emulate root ownership *only* for
# the temporary hold-state fixture; the production root-ownership guard is intact.
original_path_stat = Path.stat
fixture_path = None

def fixture_stat(self, *args, **kwargs):
    result = original_path_stat(self, *args, **kwargs)
    if fixture_path is not None and self == fixture_path:
        fields = list(result)
        fields[4] = 0  # st_uid; only the test fixture impersonates root
        return os.stat_result(fields)
    return result

with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    file = base / '.checkpoint-holds.json'
    fixture_path = file
    policy = module.RetentionPolicy(1, 1, 1, 1, 1, 30)
    verification = module.VerificationPolicy(False, '', '', '', None)
    config = module.Config(base, base / 'manager.lock', None,
                           (module.SnapshotSource('root', base / 'root'), module.SnapshotSource('@data', base / '@data')),
                           policy, verification, False, None, file, True)
    try:
        module.read_checkpoint_holds(config)
        raise AssertionError('missing hold file permitted pruning')
    except module.SnapshotError:
        pass
    file.write_text('{"schema":1,"holds":{}}')
    os.chmod(file, 0o600)
    with patch.object(Path, 'stat', fixture_stat):
        assert module.read_checkpoint_holds(config) == {}
        timestamp = '20261013-171228Z'
        u1 = '11111111-1111-1111-1111-111111111111'
        u2 = '22222222-2222-2222-2222-222222222222'
        module.write_checkpoint_holds(config, {timestamp: {'reason': 'pre-cleanup checkpoint', 'source_uuids': {'root': u1, '@data': u2}}})
        assert timestamp in module.read_checkpoint_holds(config)
        assert file.stat().st_mode & 0o777 == 0o600
        with patch.object(module, 'preflight'), patch.object(module, 'managed_snapshot_sets', return_value=(
                [('20261014-171228Z', module.parse_timestamp('20261014-171228Z')),
                 (timestamp, module.parse_timestamp(timestamp))], {})), \
             patch.object(module, 'retention_keep_set', return_value={'20261014-171228Z'}), \
             patch.object(module, 'replication_pins', return_value=set()):
            assert module.prune(config, dry_run=True) == 0, 'held checkpoint was selected for pruning'
        file.write_text('{corrupted')
        try:
            module.read_checkpoint_holds(config)
            raise AssertionError('corrupt checkpoint state permitted pruning')
        except module.SnapshotError:
            pass
    print('PASS: independent checkpoint holds persist, exclude retention deletion and fail closed')
