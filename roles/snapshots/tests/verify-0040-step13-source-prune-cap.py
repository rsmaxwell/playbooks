#!/usr/bin/env python3
"""0040 Step 13: ensure source catch-up is bounded and pins survive."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROLE = Path(__file__).resolve().parents[1]
SCRIPT = ROLE / 'files/btrfs-snapshot-manager.py'
spec = importlib.util.spec_from_file_location('btrfs_snapshot_manager_step13', SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

parent = '20261108-030011Z'
prior = '20261107-030031Z'
eligible = ['20261106-030001Z', '20261105-030001Z', '20261104-030001Z']
entries = [(parent, None), (prior, None)] + [(x, None) for x in eligible]
source = SimpleNamespace(name='@data')
config = SimpleNamespace(mode='source', sources=[source], snapshot_root=Path('/not-real'),
                         retention=object(), prune_source_names=('@data',))

class FakePath:
    def __init__(self, stamp):
        self.stamp = stamp
    def exists(self):
        return True
    def __str__(self):
        return '/synthetic/' + self.stamp


def verify(limit, dry_run, expected):
    seen = []
    removed = []
    def fake_run(argv):
        assert argv[:3] == ['btrfs', 'subvolume', 'delete']
        removed.append(argv[-1])
    def fake_validation(config, source, stamp):
        seen.append(stamp)
    patches = [
        patch.object(module, 'preflight', return_value=None),
        patch.object(module, 'managed_snapshot_sets', return_value=(entries, {})),
        patch.object(module, 'retention_keep_set', return_value=set()),
        patch.object(module, 'replication_pins', return_value=set()),
        patch.object(module, 'agreed_parent_pins', return_value=set()),
        patch.object(module, 'simplified_agreed_parent_pins', return_value={parent,prior}),
        patch.object(module, 'read_checkpoint_holds', return_value={}),
        patch.object(module, 'snapshot_path', side_effect=lambda config,source,stamp:FakePath(stamp)),
        patch.object(module, 'validate_prune_candidate', side_effect=fake_validation),
        patch.object(module, 'native_prune_subvolume_id', return_value=12345),
        patch.object(module, 'run', side_effect=fake_run),
    ]
    out = io.StringIO()
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        with contextlib.redirect_stdout(out):
            count=module.prune(config, dry_run=dry_run, max_delete=limit)
    assert count == expected
    assert seen == eligible, f'entire eligible plan must be prevalidated: {seen}'
    assert len(removed) == (0 if dry_run else expected)
    assert all(parent not in p and prior not in p for p in removed)
    if limit is not None:
        assert f'PRUNE-CAP: eligible={len(eligible)}' in out.getvalue()
    print(f'PASS: limit={limit} dry_run={dry_run} selected={count} prevalidated={len(seen)}')

verify(1, False, 1)
verify(2, False, 2)
verify(10, False, 3)
verify(32, False, 3)
verify(1, True, 1)
verify(None, False, 3) # existing direct-CLI compatibility
for invalid in (0, -1, 33, True):
    try:
        module.prune(config, max_delete=invalid)
    except module.SnapshotError:
        print(f'PASS: refused invalid limit {invalid!r}')
    else:
        raise AssertionError(f'accepted invalid limit {invalid!r}')

# A daily run may have about 24 expired hourly snapshots. Prove the
# enlarged cap can process 32, validates all 40 candidates, and never
# deletes the agreed parent or its predecessor.
from datetime import datetime, timedelta, timezone
previous_eligible, previous_entries = eligible, entries
base = datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc)
eligible = [(base - timedelta(hours=i)).strftime('%Y%m%d-%H%M%SZ') for i in range(40)]
entries = [(parent, None), (prior, None)] + [(x, None) for x in eligible]
verify(32, False, 32)
verify(32, True, 32)
eligible, entries = previous_eligible, previous_entries

service = (ROLE/'templates/btrfs-snapshot-prune.service.j2').read_text()
defaults = (ROLE/'defaults/main.yaml').read_text()
tasks = (ROLE/'tasks/main.yaml').read_text()
assert '--max-delete {{ btrfs_snapshot_prune_max_delete }}' in service
assert 'btrfs_snapshot_prune_activation_enabled: false' in defaults
assert 'btrfs_snapshot_prune_max_delete: 10' in defaults
assert 'btrfs_snapshot_prune_max_delete <= 32' in tasks
assert "state: " in tasks and "else 'stopped'" in tasks
assert 'enabled: "{{ btrfs_snapshot_prune_activation_enabled | bool }}"' in tasks
assert 'when: btrfs_snapshot_activation_enabled | bool' in tasks
assert 'name: snapshots | Enforce explicitly approved source pruning timer state' in tasks
print('PASS: capped scheduled prune + enforced paused timer across reboot')
