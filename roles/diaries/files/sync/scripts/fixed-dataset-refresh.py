#!/usr/bin/env python3
"""0036 opt-in: incrementally refresh a fixed schema-2 working directory.

This is a *verified-source* adapter, NOT the final direct NAS capture path.
The producer must already have emitted a completed schema-2 dataset.
Consumers must honour the sibling marker + flock protocol; the old 0034
publisher/pull does not automatically honour it. Never enable in production
until the Step 3/4 integration gates are closed.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def checked(*args):
    subprocess.run(args, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--destination', type=Path, required=True)
    ap.add_argument('--manifest-tool', type=Path, required=True)
    args = ap.parse_args()
    src = args.source.resolve(strict=True)
    dst = args.destination.absolute()
    tool = args.manifest_tool.resolve(strict=True)
    if dst.name != 'diaries-backup':
        ap.error('destination must be named diaries-backup')
    if src == dst or src in dst.parents or dst in src.parents:
        ap.error('source and destination must be disjoint')
    if dst.is_symlink() or src.is_symlink():
        ap.error('source/destination symlinks not supported')
    if not src.is_dir() or not (src/'dataset-manifest.json').is_file():
        ap.error('source must be a schema-2 dataset')
    if dst.exists() and not dst.is_dir():
        ap.error('destination must be a directory')
    if not dst.parent.is_dir():
        ap.error('destination parent must already exist')
    if not dst.exists():
        dst.mkdir(mode=0o700)
    lock_path = dst.parent/'.diaries-backup-fixed.lock'
    marker = dst.parent/'.diaries-backup-fixed-verified.json'
    with lock_path.open('a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Never leave an accepted marker while mutable contents change.
        marker.unlink(missing_ok=True)
        checked(sys.executable, str(tool), 'verify', '--backup-dir', str(src))
        # --checksum detects changed bytes even when mtimes/lengths coincide;
        # delayed updates reduce exposure, but this is NOT atomic. Readers need lock.
        checked('rsync', '-rltpc', '--checksum', '--delete', '--delete-delay',
                '--delay-updates', '--no-perms', '--no-owner', '--no-group',
                '--exclude=/.image-staging/', '--exclude=/.*.rsync-tmp/',
                str(src) + '/', str(dst) + '/')
        checked(sys.executable, str(tool), 'verify', '--backup-dir', str(dst),
                '--allow-fixed-working-root')
        data = (dst/'dataset-manifest.json').read_bytes()
        identity = json.loads(data)
        payload = {'schemaVersion': 1, 'backupId': identity['backupId'],
                   'manifestSha256': hashlib.sha256(data).hexdigest(),
                   'root': str(dst)}
        temp = marker.with_name(marker.name+'.tmp')
        try:
            temp.write_text(json.dumps(payload, sort_keys=True)+'\n')
            os.replace(temp, marker)
        finally:
            temp.unlink(missing_ok=True)
        print('PASS: fixed working dataset verified:', payload['backupId'])


if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.CalledProcessError, BlockingIOError, ValueError) as exc:
        print('BLOCKED: fixed refresh failed; verified marker absent:', exc, file=sys.stderr)
        sys.exit(1)
