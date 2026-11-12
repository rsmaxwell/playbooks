#!/usr/bin/env python3
"""0040 Step 12.2: source-only fail-closed receiver deletion boundary regression.

No Btrfs commands or installed receiver are invoked. No production mutations.
"""
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
import inspect

MANAGER = Path(__file__).resolve().parents[2] / 'snapshots/files/btrfs-snapshot-manager.py'


def main():
    assert MANAGER.is_file(), f'Missing source manager: {MANAGER}'
    name = 'step12_2_snapshot_manager'
    loader = importlib.machinery.SourceFileLoader(name, str(MANAGER))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)

    parent = '20261026-080000Z'
    newer = '20261026-090000Z'
    older = '20261026-070000Z'
    state = Path('/nonexistent-step12-2-receiver-state')
    config = SimpleNamespace(mode='receiver', receiver_state_dir=state,
                             writer_lock_path=state / 'writer.lock')
    callbacks = {'pin': 0, 'delete': 0, 'inventory': 0}

    def unexpected_pin():
        callbacks['pin'] += 1
        raise AssertionError('source-pin callback reached')

    def unexpected_delete(_path):
        callbacks['delete'] += 1
        raise AssertionError('delete callback reached')

    def inventory(_config):
        callbacks['inventory'] += 1
        raise RuntimeError('INVENTORY_REACHED')

    args = dict(protected_stamp=parent,
                expected_parent_uuid='11111111-2222-3333-4444-555555555555',
                verify_source_pin=unexpected_pin, delete_subvolume=unexpected_delete)
    with mock.patch.object(mod, 'receiver_inventory', side_effect=inventory), \
         mock.patch.object(mod, 'receiver_journal_write', side_effect=AssertionError('journal called')):
        for candidate in (parent, newer):
            try:
                mod.receiver_delete_one_locked(config, candidate, **args)
            except mod.SnapshotError as exc:
                assert 'parent or newer' in str(exc), str(exc)
            else:
                raise AssertionError(f'Boundary allowed {candidate}')
            assert callbacks == {'pin': 0, 'delete': 0, 'inventory': 0}, callbacks
        for candidate in ('INVALID', '20261026-070000Z/../x'):
            try:
                mod.receiver_delete_one_locked(config, candidate, **args)
            except mod.SnapshotError:
                pass
            else:
                raise AssertionError(f'Invalid identity accepted: {candidate}')
            assert callbacks == {'pin': 0, 'delete': 0, 'inventory': 0}, callbacks
        try:
            mod.receiver_delete_one_locked(config, older, **args)
        except RuntimeError as exc:
            assert str(exc) == 'INVENTORY_REACHED', str(exc)
        else:
            raise AssertionError('Older candidate did not reach next safety gate')
        assert callbacks == {'pin': 0, 'delete': 0, 'inventory': 1}, callbacks
    assert 'live common-parent coordination not implemented' in (
        mod.receiver_guarded_prune.__doc__ or ''
    ) or 'receiver pruning blocked' in inspect.getsource(mod.receiver_guarded_prune)
    print('PASS: protected parent and newer candidate fail before inventory, journal and callbacks')
    print('PASS: malformed identities fail closed; older candidate reaches next safety gate')
    print('PASS: production guarded-prune entry point remains blocked')
    print('LIMIT: source-only mock regression; no receiver locks, receipts, pins, or Btrfs deletion')


if __name__ == '__main__':
    main()
