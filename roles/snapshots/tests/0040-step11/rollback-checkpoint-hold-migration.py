#!/usr/bin/env python3
"""0040 Step 11 one-time rollback. Preview only unless explicitly authorised.

Restore the original two-source checkpoint record only with the original
root+@data manager configuration and stopped snapshot creation/pruning.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from importlib.machinery import SourceFileLoader
import subprocess
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_loader('hold_commit', SourceFileLoader('hold_commit', str(HERE / 'commit-checkpoint-hold-migration.py')))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def rollback_transaction(holds, root, backup, *, read=m.read_candidate, replace=m.secure_write):
    """Pure transaction core; caller validates production context and locks."""
    m.validate_file(backup)
    original = backup.read_bytes()
    proposed = m.preview(json.loads(original), m.snapshot_uuid, root)
    expected = (json.dumps(proposed, indent=2, sort_keys=True) + '\n').encode()
    m.validate_file(holds)
    if holds.read_bytes() != expected:
        raise m.UnsafeState('current holds do not exactly match committed migration')
    replace(holds, original)
    if holds.read_bytes() != original:
        raise m.UnsafeState('rollback readback mismatch')
    return original


def main():
    parser = argparse.ArgumentParser(description='0040 one-time hold rollback; preview by default')
    parser.add_argument('--commit', action='store_true')
    parser.add_argument('--authorise', default='')
    args = parser.parse_args()
    holds = Path('/media/usb/@snapshots/.checkpoint-holds.json')
    root = Path('/media/usb/@snapshots')
    backup = holds.with_name('.checkpoint-holds.0040-step11-before.json')
    config_path = Path('/etc/btrfs-snapshot-manager.json')
    try:
        if os.geteuid() != 0:
            raise m.UnsafeState('must run as root')
        if config_path.is_symlink():
            raise m.UnsafeState('configuration symlink refused')
        config = json.loads(config_path.read_text())
        if {s['name'] for s in config['sources']} != {'root', '@data'}:
            raise m.UnsafeState('restore two-source manager configuration FIRST')
        if config.get('snapshot_root') != str(root) or config.get('checkpoint_holds', {}).get('path') != str(holds) or config.get('checkpoint_holds', {}).get('required') is not True:
            raise m.UnsafeState('unexpected configuration')
        m.validate_file(backup)
        m.validate_file(holds)
        original = backup.read_bytes()
        proposed = m.preview(json.loads(original), m.snapshot_uuid, root)
        expected = (json.dumps(proposed, indent=2, sort_keys=True) + '\n').encode()
        if holds.read_bytes() != expected:
            raise m.UnsafeState('current holds not equal to expected migrated state')
        print('ROLLBACK PREVIEW: original_sha256=', hashlib.sha256(original).hexdigest())
        if not args.commit:
            print('PREVIEW ONLY — NO FILES MODIFIED')
            return 0
        if args.authorise != '0040-STEP11-ROLLBACK-ONLY':
            raise m.UnsafeState('rollback authorisation missing')
        for unit in ('btrfs-snapshot-create.timer', 'btrfs-snapshot-prune.timer', 'btrfs-snapshot-create.service', 'btrfs-snapshot-prune.service'):
            if subprocess.run(['systemctl', 'is-active', '--quiet', unit]).returncode == 0:
                raise m.UnsafeState('timer/service still active: ' + unit)
        lockfd = os.open(config['lock_path'], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            import fcntl
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            rollback_transaction(holds, root, backup)
        finally:
            os.close(lockfd)
        print('ROLLBACK COMPLETED; original backup retained')
        return 0
    except (m.UnsafeState, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print('REFUSED:', exc, file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
