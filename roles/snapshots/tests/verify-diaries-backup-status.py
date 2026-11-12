#!/usr/bin/env python3
"""Synthetic non-mutating regression for backup status aggregation."""
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

module_file = Path(__file__).resolve().parents[1] / 'files' / 'diaries-backup-status.py'
spec = importlib.util.spec_from_file_location('backup_status', module_file)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / 'backup').mkdir()
    marker = {'backupId': '20261014-010000Z', 'logicalDataset': 'production',
              'state': 'verified-published', 'snapshotEligible': True, 'verifiedAt': 'now'}
    (root / 'backup' / '.verified.json').write_text(json.dumps(marker))
    config = {'sources': [{'name': '@data', 'path': str(root)}],
              'verification': {'required': True, 'source_name': '@data', 'marker_relative_path': 'backup/.verified.json'}}
    assert m.read_marker(config)['ok']
    config['verification']['marker_relative_path'] = '../bad'
    assert not m.read_marker(config)['ok']
    config['verification']['marker_relative_path'] = 'backup/.verified.json'
    (root / 'config.json').write_text(json.dumps(config))
    class Args:
        pass
    args = Args()
    args.config = str(root / 'config.json')
    args.manager = '/fake/manager'; args.history = '/fake/history'; args.push = '/fake/simplified'
    args.limit = 5
    def fake_command(argv, timeout=40):
        if argv[-2:] != ['sender', 'status'] and 'status' in argv:
            return {'ok': True, 'stdout': 'complete_timestamp_sets=2;incomplete_timestamp_sets=0'}
        if '--json' in argv:
            return {'ok': False, 'stdout': '', 'error': 'history not configured'}
        if argv[-2:] == ['sender', 'status']:
            return {'ok': True, 'stdout': json.dumps({
                'receiver_parent_verified': True, 'relation': 'equal',
                'receiver': {'parent': {'timestamp': '20261014-010000Z', 'uuid': '123'}},
                'preflight': {'action': 'up-to-date', 'source': None,
                              'parent': '20261014-010000Z'}})}
        raise AssertionError(argv)
    with patch.object(m, 'command', side_effect=fake_command), patch.object(m.os, 'geteuid', return_value=0):
        result = m.report(args)
    assert result['snapshot']['ok']
    assert result['lastVerifiedPull']['data']['backupId'] == '20261014-010000Z'
    assert result['offsite']['latest']['snapshot'] == '20261014-010000Z'
    assert result['offsite']['identity_verified'] is True
    assert result['replicationPreflight']['data']['action'] == 'up-to-date'
    assert not result['history']['ok']
    m.display(result)
    def stale_or_invalid(argv, timeout=40):
        if argv[-2:] == ['sender', 'status']:
            return {'ok': True, 'stdout': json.dumps({'receiver_parent_verified': False})}
        return fake_command(argv, timeout)
    with patch.object(m, 'command', side_effect=stale_or_invalid), patch.object(m.os, 'geteuid', return_value=0):
        invalid = m.report(args)
    assert not invalid['replicationPreflight']['ok']
    assert not invalid['offsite']['ok']
    # An ordinary operator may only use specifically authorised sudo -n;
    # this command must never grant itself privileges or start a cycle.
    seen = []
    def nonroot_command(argv, timeout=40):
        seen.append(argv)
        return fake_command(argv, timeout)
    with patch.object(m, 'command', side_effect=nonroot_command), patch.object(m.os, 'geteuid', return_value=1000):
        result = m.report(args)
    assert result['offsite']['ok']
    assert ['sudo', '-n', '/fake/simplified', 'sender', 'status'] in seen
    assert all('cycle' not in argv and '--preflight' not in argv and '--list' not in argv for argv in seen)
print('PASS: simplified read-only aggregate, invalid receiver refusal, and verified marker handling')
