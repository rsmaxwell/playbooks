#!/usr/bin/env python3
"""0049: Diaries-only summary regression; infrastructure data belongs in btrfs-backup-status."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

module_file = Path(__file__).resolve().parents[1] / 'files' / 'diaries-backup-status.py'
spec = importlib.util.spec_from_file_location('diaries_status_0049', module_file)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
rows = [{'logicalDataset': 'production', 'backupId': '20261116-014500Z',
         'firstRetainedSnapshot': '20261116-020000Z', 'lastRetainedSnapshot': '20261116-100000Z',
         'snapshots': 9, 'status': 'verified'}]
args = SimpleNamespace(config='/fixture', history='/history', limit=5)
with patch.object(m, 'inspect_history', return_value={'backups': rows, 'warnings': []}):
    data = m.report(args)
assert data['health'] == 'healthy'
assert data['distinctBackups'] == 1 and data['retainedOccurrences'] == 9
assert data['latest']['backupId'] == '20261116-014500Z'
assert not any(k in data for k in ('snapshot', 'replication', 'lastVerifiedPull', 'offsite'))
output = io.StringIO()
with contextlib.redirect_stdout(output):
    m.display(data)
assert 'RECENT DIARIES BACKUPS' in output.getvalue()
assert 'Manifest identity' in output.getvalue()
assert '20261116-014500Z' in output.getvalue()
assert 'QGROUP' not in output.getvalue()
assert json.loads(json.dumps(data, indent=2))['component'] == 'diaries'
with patch.object(m, 'inspect_history', return_value={'backups': [], 'warnings': []}):
    empty = m.report(args)
    out = io.StringIO()
    with contextlib.redirect_stdout(out): m.display(empty)
    assert 'No retained backups found' in out.getvalue()
with patch.object(m, 'inspect_history', side_effect=RuntimeError('history failed')):
    failed = m.report(args)
assert failed['health'] == 'error'
print('PASS: 0049 Diaries status excludes infrastructure, aligns history and handles empty/errors')
