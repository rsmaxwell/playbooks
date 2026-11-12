#!/usr/bin/env python3
"""Disposable 0036 fixed-destination receive lifecycle/lock regression."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / 'files/backup-machine/diaries-pull.py'
spec = importlib.util.spec_from_file_location('diaries_pull_0036', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix='0036-mars-receive-') as temp:
    root = Path(temp)
    dst_parent = root / 'backup/pluto'
    dst_parent.mkdir(parents=True)
    published = dst_parent / 'diaries-backup'
    marker = root / 'backup/.diaries-snapshot-verified.json'
    lock = root / 'backup/.btrfs-snapshot-writer.lock'
    marker.write_text('{"snapshotEligible":true}\n')
    args = SimpleNamespace(fixed_source_guard=Path('/remote/guard.py'),
        verification_marker=marker,repository_lock=lock,source_parent=Path('/remote/data'),
        host='pluto',rsync='rsync',ssh='ssh',manifest_tool=root/'manifest.py')
    (root/'manifest.py').write_text('placeholder')
    src = Path('/remote/data/diaries-backup')
    def success(command, check):
        if command[0]=='rsync':
            assert '--delete' in command
            assert '--rsync-path=' in ' '.join(command)
            published.mkdir(exist_ok=True)
            (published/'database').mkdir(exist_ok=True)
            (published/'files').mkdir(exist_ok=True)
            (published/'dataset-manifest.json').write_text(json.dumps({'backupId':'20261016-120000Z','logicalDataset':'production'}))
            assert not marker.exists(), 'marker must be revoked before receive'
        else:
            assert '--allow-fixed-working-root' in command
            assert not marker.exists(), 'marker must stay revoked before validation'
    with patch.object(module.subprocess, 'run',side_effect=success):
        module.fixed_destination_receive(args,published,src,'backup/pluto/diaries-backup','backup/.diaries-snapshot-verified.json')
    payload=json.loads(marker.read_text())
    assert payload['snapshotEligible'] is True and payload['backupId']=='20261016-120000Z'
    assert payload['datasetRelativePath']=='backup/pluto/diaries-backup'
    print('PASS: fixed receive uses guarded rsync --delete and only marks after validation')
    # A subsequent failed transfer must revoke eligibility and leave existing working files recoverable.
    with patch.object(module.subprocess,'run',side_effect=RuntimeError('interrupted')):
        try:
            module.fixed_destination_receive(args,published,src,'backup/pluto/diaries-backup','backup/.diaries-snapshot-verified.json')
            raise AssertionError('interruption not reported')
        except RuntimeError as exc:
            assert str(exc)=='interrupted'
    assert not marker.exists() and (published/'dataset-manifest.json').is_file()
    print('PASS: interrupted receive removes eligibility while retaining working dataset')
    published.rename(dst_parent/'previous')
    published.symlink_to('previous',target_is_directory=True)
    try:
        module.fixed_destination_receive(args,published,src,'backup/pluto/diaries-backup','backup/.diaries-snapshot-verified.json')
        raise AssertionError('legacy symlink accepted')
    except RuntimeError as exc:
        assert 'symlink' in str(exc)
    print('PASS: legacy publication symlink refused; historical directory untouched')
