#!/usr/bin/env python3
"""0047: rsync copies per-entry source modes, with no --chmod override."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import yaml

role = Path(__file__).resolve().parents[1]
contract = json.loads((role / 'source-modes.json').read_text())
assert contract['schema'] == '0047-collection-source-modes-v1'
entries = contract['entries']
assert len(entries) == 14
for task, expected_src in [('install_user_scripts.yaml', 'backup/'),
                           ('install_machine_scripts.yaml', 'backup-machine/')]:
    tasks = yaml.safe_load((role / 'tasks' / task).read_text())
    copies = [task['ansible.posix.synchronize'] for task in tasks
              if 'ansible.posix.synchronize' in task]
    assert len(copies) == 1
    sync = copies[0]
    assert sync.get('archive') is True
    assert sync['src'] == expected_src
    opts = sync['rsync_opts']
    assert '--omit-dir-times' in opts
    assert not any('--chmod' in option or '--no-perms' in option for option in opts)
for entry in entries:
    relative = Path(entry['path'])
    assert not relative.is_absolute() and '..' not in relative.parts
    assert relative.parts[0] == 'files'
    source = role / relative
    assert source.resolve(strict=True).is_relative_to((role / 'files').resolve())
    assert not source.is_symlink()
    st = source.stat()
    assert (stat.S_ISREG(st.st_mode) if entry['kind'] == 'file'
            else stat.S_ISDIR(st.st_mode)), entry['path']
    actual = f'{stat.S_IMODE(st.st_mode):04o}'
    assert actual == entry['mode'], (
        f"Source mode mismatch: {entry['path']} actual={actual} "
        f"expected={entry['mode']} (restore source metadata before deploying)")
    if entry['kind'] == 'file':
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry['sha256']

# Disposable rsync test verifies mode preservation followed by idempotence.
with tempfile.TemporaryDirectory(prefix='0047-source-rsync-') as temp:
    source = Path(temp) / 'source'
    dest = Path(temp) / 'dest'
    (source / 'home').mkdir(parents=True)
    (dest / 'home').mkdir(parents=True)
    (source / 'home' / 'includes').write_text('item\n')
    (dest / 'home' / 'includes').write_text('item\n')
    for path, mode in [(source, 0o750), (source / 'home', 0o750),
                       (source / 'home' / 'includes', 0o664), (dest, 0o755),
                       (dest / 'home', 0o755), (dest / 'home' / 'includes', 0o644)]:
        os.chmod(path, mode)
    cmd = ['rsync', '-a', '--omit-dir-times', '--itemize-changes',
           str(source) + '/', str(dest) + '/']
    first = subprocess.run(cmd, check=True, text=True, capture_output=True)
    assert first.stdout.strip(), 'Expected initial mode corrections'
    assert stat.S_IMODE((dest / 'home').stat().st_mode) == 0o750
    assert stat.S_IMODE((dest / 'home' / 'includes').stat().st_mode) == 0o664
    second = subprocess.run(cmd, check=True, text=True, capture_output=True)
    assert not second.stdout.strip(), second.stdout
print('PASS: no rsync --chmod; 14 source modes and hashes match 0045; '
      'rsync propagates source modes and second run is idempotent')
