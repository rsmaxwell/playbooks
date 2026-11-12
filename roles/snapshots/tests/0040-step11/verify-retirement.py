#!/usr/bin/env python3
"""Offline manifest and refusal regressions (no Btrfs commands, no deletion)."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).with_name('retire-historical-root.py')
spec = importlib.util.spec_from_file_location('retire0040', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
manifest = json.loads(path.with_name('root-retirement-manifest.json').read_text())
entries = m.validate_manifest(manifest)
assert len(entries) == 63
assert entries[0]['timestamp'] == '20261011-230026Z'
assert entries[-1]['timestamp'] == '20261025-190006Z'

for change in ('duplicate', 'path', 'uuid', 'count', 'id', 'order'):
    broken = json.loads(json.dumps(manifest))
    if change == 'duplicate': broken['snapshots'][1]['timestamp'] = broken['snapshots'][0]['timestamp']
    if change == 'path': broken['snapshots'][0]['path'] = '/media/usb/@snapshots/@data/20261011-230026Z'
    if change == 'uuid': broken['snapshots'][0]['uuid'] = 'bad'
    if change == 'count': broken['snapshots'].pop()
    if change == 'id': broken['snapshots'][1]['id'] = broken['snapshots'][0]['id']
    if change == 'order': broken['snapshots'].reverse()
    try:
        m.validate_manifest(broken)
    except m.Refusal:
        pass
    else:
        raise AssertionError(f'Fail-open for {change}')

# Production config contract: flags belong to the sole source record, not
# deprecated or imaginary top-level required/creation lists.
valid_source = {'name': '@data', 'path': '/media/usb/@data',
                'required': True, 'creation': True, 'prune': True}

def config_guard(config):
    # Stop immediately after source validation so no host-specific Btrfs access
    # is needed in this offline regression.
    with patch.object(m, 'read_json', return_value=config), \
         patch.object(type(m.ROOT), 'is_symlink', side_effect=m.Refusal('SOURCE_CONFIG_ACCEPTED')):
        try:
            m.base_preflight(entries)
        except m.Refusal as exc:
            return str(exc)
    raise AssertionError('Config check unexpectedly ran through offline boundary')

assert config_guard({'sources': [dict(valid_source)]}) == 'SOURCE_CONFIG_ACCEPTED'
for field in ('required', 'creation', 'prune'):
    for bad in (False, None, 'true', 1):
        candidate = dict(valid_source)
        candidate[field] = bad
        assert 'Unexpected @data source' in config_guard({'sources': [candidate]}), (field, bad)
for bad in ('/media/usb', '/media/usb/@snapshots/root'):
    candidate = dict(valid_source, path=bad)
    assert 'Unexpected @data source' in config_guard({'sources': [candidate]})
assert 'Manager is not @data-only' in config_guard({'sources': [dict(valid_source, name='root')]})
assert 'Manager is not @data-only' in config_guard({'sources': [dict(valid_source), dict(valid_source)]})
# Regression fixture from mars, 2026-10-26 08:34: Btrfs list from the
# filesystem mount includes root snapshots interleaved with @data siblings.
fixture = [
    'ID 20556 gen 60118 top level 20446 path @snapshots/root/20261011-230026Z',
    'ID 20557 gen 60119 top level 20446 path @snapshots/@data/20261011-230026Z',
    'ID 20602 gen 60191 top level 20446 path @snapshots/root/20261012-230026Z',
]
assert m.discover_root_candidates(fixture) == [
    '20261011-230026Z', '20261012-230026Z'
]
try:
    m.discover_root_candidates(fixture + [
        'ID 99999 gen 1 top level 20446 path @snapshots/root/20261011-230026Z/child'
    ])
except m.Refusal as exc:
    assert 'Nested subvolume' in str(exc)
else:
    raise AssertionError('Nested root subvolume was accepted')
# Verify the exact production command is used as the discovery root.
import inspect
assert "run('btrfs', 'subvolume', 'list', '/media/usb')" in inspect.getsource(m.base_preflight)
print('PASS: immutable inventory (63), config/refusal tests, and production Btrfs listing fixture')

# Commit journal tests are mock-only: no systemd interaction or Btrfs deletion.
import tempfile
from contextlib import ExitStack

first = entries[:2]
def read_events(receipt):
    return [json.loads(line) for line in receipt.read_text().splitlines()]

with tempfile.TemporaryDirectory() as directory:
    receipt = Path(directory) / 'receipt.jsonl'
    commands = []
    def fake_delete(*command):
        assert command[:3] == ('btrfs', 'subvolume', 'delete')
        assert read_events(receipt)[-1]['event'] == 'DELETE_INTENT'
        commands.append(command)
        return ''
    with patch.object(m, 'protection_preflight'), \
         patch.object(m, 'commit_replication_exclusion'), \
         patch.object(m, 'metadata', side_effect=lambda path: (
             next(e['id'] for e in first if e['timestamp'] == path.name),
             next(e['uuid'] for e in first if e['timestamp'] == path.name),
             ['readonly'])), \
         patch.object(m, 'ROOT', Path(directory)), \
         patch.object(m, 'run', side_effect=fake_delete):
        for item in first:
            (Path(directory) / item['timestamp']).mkdir()
        with receipt.open('w') as out:
            m.delete_with_receipt(first, out)
    events = read_events(receipt)
    assert [e['event'] for e in events] == [
        'BEGIN', 'DELETE_INTENT', 'DELETED', 'DELETE_INTENT', 'DELETED', 'COMPLETE']
    assert len(commands) == 2
    assert len(events[0]['manifest_sha256']) == 64

with tempfile.TemporaryDirectory() as directory:
    receipt = Path(directory) / 'receipt.jsonl'
    target = Path(directory) / first[0]['timestamp']
    target.mkdir()
    def refused_delete(*command):
        assert read_events(receipt)[-1]['event'] == 'DELETE_INTENT'
        raise m.Refusal('Injected Btrfs failure')
    with patch.object(m, 'protection_preflight'), \
         patch.object(m, 'commit_replication_exclusion'), \
         patch.object(m, 'metadata', return_value=(first[0]['id'], first[0]['uuid'], ['readonly'])), \
         patch.object(m, 'ROOT', Path(directory)), \
         patch.object(m, 'run', side_effect=refused_delete):
        with receipt.open('w') as out:
            try:
                m.delete_with_receipt(first[:1], out)
            except m.Refusal as exc:
                assert 'Injected Btrfs failure' in str(exc)
            else:
                raise AssertionError('Btrfs failure was ignored')
    assert [e['event'] for e in read_events(receipt)] == ['BEGIN', 'DELETE_INTENT']

# In a commit, the service must be masked AND inactive; preview needs neither mask nor change.
with patch.object(m, 'systemd_state', side_effect=[('masked-runtime', 1), ('inactive', 3)]):
    m.commit_replication_exclusion()
with patch.object(m, 'systemd_state', return_value=('disabled', 1)):
    try:
        m.commit_replication_exclusion()
    except m.Refusal as exc:
        assert 'runtime-masked' in str(exc)
    else:
        raise AssertionError('Unmasked service was accepted for commit')
print('PASS: durable intent/completion ordering, interrupted deletion receipt and replication gate')
