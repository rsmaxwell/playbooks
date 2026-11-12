#!/usr/bin/env python3
"""Guard a fixed schema-2 source while running the rsync server (no data writes).

Invoked by remote rsync as: guard.py --lock LOCK --marker MARKER
--dataset DATASET -- rsync --server ...
The shared flock covers both marker/manifest validation and the entire rsync.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys


def check(marker_path: Path, dataset: Path):
    if marker_path.is_symlink() or not marker_path.is_file():
        raise ValueError('accepted fixed-dataset marker is missing or unsafe')
    if dataset.is_symlink() or not dataset.is_dir() or dataset.name != 'diaries-backup':
        raise ValueError('fixed dataset missing, unsafe, or incorrectly named')
    manifest_path = dataset / 'dataset-manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('fixed dataset manifest missing or unsafe')
    marker = json.loads(marker_path.read_text())
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    if marker.get('schemaVersion') != 1 or marker.get('root') != str(dataset) or not isinstance(marker.get('backupId'), str):
        raise ValueError('marker contract invalid')
    if manifest.get('backupId') != marker.get('backupId'):
        raise ValueError('marker backup ID differs from manifest')
    if hashlib.sha256(raw).hexdigest() != marker.get('manifestSha256'):
        raise ValueError('marker digest differs from manifest')


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument('--lock', type=Path, required=True)
    cli.add_argument('--marker', type=Path, required=True)
    cli.add_argument('--dataset', type=Path, required=True)
    cli.add_argument('command', nargs=argparse.REMAINDER)
    args = cli.parse_args()
    if not args.command or args.command[0] != '--' or len(args.command) < 2 or Path(args.command[1]).name != 'rsync':
        raise ValueError('only rsync remote server execution is permitted')
    if not all(path.is_absolute() for path in (args.lock, args.marker, args.dataset)):
        raise ValueError('absolute paths required')
    if args.marker.parent != args.lock.parent or args.dataset.parent != args.lock.parent:
        raise ValueError('fixed lock, marker and dataset must share a parent')
    if args.lock.is_symlink() or not args.lock.is_file():
        raise ValueError('existing fixed capture lock required')
    with args.lock.open('rb') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_SH)
        check(args.marker, args.dataset)
        # The descriptor remains open across exec: Python marks descriptors
        # non-inheritable by default, so explicitly clear FD_CLOEXEC.
        os.set_inheritable(lock.fileno(), True)
        os.execvp(args.command[1], args.command[1:])


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'BLOCKED: fixed source not accepted: {exc}', file=sys.stderr)
        sys.exit(3)
