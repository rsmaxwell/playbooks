#!/usr/bin/env python3
"""Verified mars pull of an already-published pluto Diaries generation.

The receive is staged and independently schema-2 verified before the mars stable
publication advances. The whole-backup writer lock is held for the entire
receive/publication/marker handoff so 0035 cannot snapshot a partial state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import shlex
import subprocess
import sys
import tempfile


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def relative_inside(path: Path, root: Path, label: str) -> str:
    resolved_root = root.resolve(strict=True)
    lexical = path.absolute()
    try:
        rel = lexical.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f'{label} must be below snapshot source root {resolved_root}: {lexical}') from exc
    require(all(part not in ('', '.', '..') for part in PurePosixPath(rel.as_posix()).parts), f'unsafe {label} relative path')
    return rel.as_posix()


def atomic_marker(path: Path, document: dict) -> None:
    require(path.is_absolute(), f'absolute marker path required: {path}')
    require(path.parent.is_dir() and not path.parent.is_symlink(), f'marker parent missing/unsafe: {path.parent}')
    require(not path.is_symlink(), f'refusing marker symlink: {path}')
    temp = path.parent / ('.' + path.name + '.tmp-' + str(os.getpid()))
    try:
        with temp.open('x', encoding='utf-8') as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o640)
        os.replace(temp, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if temp.exists():
            temp.unlink()


def fixed_destination_receive(args, published: Path, source: Path, dataset_relative: str, marker_relative: str) -> None:
    """0036 opt-in mutable Btrfs working copy. Historical read-only snapshots are untouched."""
    require(args.fixed_source_guard is not None, 'fixed destination requires verified guarded source')
    require(args.fixed_source_guard.is_absolute(), 'absolute remote guard path required')
    require(not published.is_symlink(), 'fixed destination may not be legacy publication symlink')
    require(not published.exists() or published.is_dir(), 'fixed destination must be a directory')
    require(args.verification_marker.parent != published and published not in args.verification_marker.parents,
            'snapshot marker must be outside mutable dataset')
    lock = args.source_parent / '.diaries-backup-fixed.lock'
    marker = args.source_parent / '.diaries-backup-fixed-verified.json'
    remote_path = ('python3 ' + shlex.quote(str(args.fixed_source_guard)) +
                   ' --lock ' + shlex.quote(str(lock)) +
                   ' --marker ' + shlex.quote(str(marker)) +
                   ' --dataset ' + shlex.quote(str(source)) + ' -- rsync')
    with args.repository_lock.open('a+') as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        # Revoke snapshot eligibility BEFORE any mutable receive. Failure remains fail-closed.
        require(not args.verification_marker.is_symlink(), 'snapshot marker symlink refused')
        args.verification_marker.unlink(missing_ok=True)
        dirfd = os.open(args.verification_marker.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        published.mkdir(mode=0o750, exist_ok=True)
        require(not published.is_symlink(), 'fixed destination symlink refused')
        remote_src = args.host + ':' + shlex.quote(str(source) + '/')
        subprocess.run([args.rsync, '-a', '--safe-links', '--delete', '--protect-args',
                        '--rsync-path=' + remote_path, '-e', args.ssh,
                        remote_src, str(published) + '/'], check=True)
        subprocess.run([sys.executable, str(args.manifest_tool), 'verify',
                        '--backup-dir', str(published), '--allow-fixed-working-root'], check=True)
        manifest_path = published / 'dataset-manifest.json'
        require(manifest_path.is_file() and not manifest_path.is_symlink(), 'missing/unsafe fixed manifest')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        backup_id, logical_dataset = manifest.get('backupId'), manifest.get('logicalDataset')
        require(isinstance(backup_id, str) and backup_id and '/' not in backup_id and
                backup_id not in ('.', '..') and not backup_id.startswith('.'), 'unsafe backup ID')
        require(isinstance(logical_dataset, str) and logical_dataset, 'missing logical dataset')
        atomic_marker(args.verification_marker, {
            'format': 1, 'feature': '0034-FEAT/0035-FEAT',
            'state': 'verified-published', 'snapshotEligible': True,
            'backupId': backup_id, 'logicalDataset': logical_dataset,
            'datasetRelativePath': dataset_relative,
            'manifestSha256': sha256_file(manifest_path),
            'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            'sourceIdentity': f'{args.host}:{source}',
        })
        print('VERIFIED_FIXED_RECEIVE')
        print(json.dumps({'backupId': backup_id, 'logicalDataset': logical_dataset,
                          'datasetRelativePath': dataset_relative, 'snapshotEligible': True,
                          'destination': str(published)}, sort_keys=True))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--host', required=True, help='configured ssh host alias of pluto')
    cli.add_argument('--source-parent', type=Path, required=True, help='pluto publisher parent')
    cli.add_argument('--destination-parent', type=Path, required=True, help='mars target parent on Btrfs')
    cli.add_argument('--snapshot-source-root', type=Path, required=True, help='local source subvolume root captured by 0035')
    cli.add_argument('--verification-marker', type=Path, required=True, help='whole-backup verified marker written after full validation')
    cli.add_argument('--repository-lock', type=Path, required=True, help='whole-backup writer/snapshot flock path')
    cli.add_argument('--publisher', type=Path, required=True, help='local complete-dataset-publisher.py')
    cli.add_argument('--manifest-tool', type=Path, required=True)
    cli.add_argument('--fixed-source-guard', type=Path, help='opt-in remote fixed-source guard; does not enable fixed-destination receive')
    cli.add_argument('--ssh', default='ssh')
    cli.add_argument('--rsync', default='rsync')
    cli.add_argument('--preflight', action='store_true')
    cli.add_argument('--fixed-destination', action='store_true',
                     help='0036 opt-in rsync --delete into Btrfs working dataset; no generation publisher')
    args = cli.parse_args()
    for path in (
        args.source_parent, args.destination_parent, args.snapshot_source_root,
        args.verification_marker, args.repository_lock, args.publisher, args.manifest_tool,
    ):
        require(path.is_absolute(), f'absolute path required: {path}')
    require(not args.source_parent.is_symlink(), 'remote source parent must be configured as a real directory')
    require(args.host and not args.host.startswith('-') and all(c.isalnum() or c in '._@-' for c in args.host), 'invalid ssh host')
    require(args.destination_parent.is_dir() and not args.destination_parent.is_symlink(), 'destination parent must exist and not be a symlink')
    require(args.snapshot_source_root.is_dir() and not args.snapshot_source_root.is_symlink(), 'snapshot source root must exist and not be a symlink')
    require(args.manifest_tool.is_file(), 'manifest helper missing')
    if not args.fixed_destination:
        require(args.publisher.is_file(), 'publisher helper missing')
    require(args.verification_marker.parent == args.repository_lock.parent, 'verification marker and repository lock must share a parent')
    require(args.verification_marker.parent.is_dir() and not args.verification_marker.parent.is_symlink(), 'verification parent missing/unsafe')

    published = args.destination_parent / 'diaries-backup'
    source = args.source_parent / 'diaries-backup'
    remote_lock = args.source_parent / '.diaries-backup.lock'
    dataset_relative = relative_inside(published, args.snapshot_source_root, 'published dataset')
    marker_relative = relative_inside(args.verification_marker, args.snapshot_source_root, 'verification marker')
    require(marker_relative.rsplit('/', 1)[0] == relative_inside(args.repository_lock.parent, args.snapshot_source_root, 'repository lock parent'),
            'marker/lock parent mapping mismatch')

    # Preflight must not require remote writable access or create local staging/locks.
    if args.preflight and args.fixed_destination:
        require(args.fixed_source_guard is not None, 'fixed destination requires guarded source')
        require(not published.is_symlink(), 'fixed destination must not be legacy symlink')
        print(f'PREFLIGHT OK: fixed dataset={published}; marker={args.verification_marker}; no writes')
        return
    if args.preflight:
        subprocess.run([sys.executable, str(args.publisher), '--published-root', str(published), 'preflight'], check=True)
        print(f'PREFLIGHT OK: datasetRelativePath={dataset_relative}; markerRelativePath={marker_relative}; no transfer/publication/snapshot')
        return

    if args.fixed_source_guard is not None:
        require(args.fixed_source_guard.is_absolute(), 'absolute remote guard path required')

    if args.fixed_destination:
        fixed_destination_receive(args, published, source, dataset_relative, marker_relative)
        return

    # The whole-backup EX lock prevents any 0035 snapshot creation while the
    # writable receive is staged, verified, published and marked eligible.
    with args.repository_lock.open('a+') as repository_lock:
        fcntl.flock(repository_lock.fileno(), fcntl.LOCK_EX)
        # Remote rsync process also holds the pluto publisher SH lock before
        # dereferencing the stable source pointer. A pluto publisher waits.
        if args.fixed_source_guard is not None:
            fixed_lock = args.source_parent / '.diaries-backup-fixed.lock'
            fixed_marker = args.source_parent / '.diaries-backup-fixed-verified.json'
            remote_rsync_path = ('python3 ' + shlex.quote(str(args.fixed_source_guard)) +
                                 ' --lock ' + shlex.quote(str(fixed_lock)) +
                                 ' --marker ' + shlex.quote(str(fixed_marker)) +
                                 ' --dataset ' + shlex.quote(str(source)) + ' -- rsync')
        else:
            remote_rsync_path = 'flock -s ' + shlex.quote(str(remote_lock)) + ' rsync'
        with tempfile.TemporaryDirectory(prefix='.diaries-pull-', dir=args.destination_parent) as temp:
            temp_path = Path(temp)
            incoming = temp_path / 'incoming'
            incoming.mkdir()
            remote_src = args.host + ':' + shlex.quote(str(source) + '/')
            cmd = [args.rsync, '-a', '--safe-links', '--delete', '--protect-args',
                   '--rsync-path=' + remote_rsync_path, '-e', args.ssh,
                   remote_src, str(incoming) + '/']
            subprocess.run(cmd, check=True)
            manifest_path = incoming / 'dataset-manifest.json'
            require(manifest_path.is_file() and not manifest_path.is_symlink(), 'received manifest missing/unsafe')
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            backup_id = manifest.get('backupId')
            logical_dataset = manifest.get('logicalDataset')
            require(isinstance(backup_id, str) and backup_id and '/' not in backup_id and backup_id not in ('.', '..') and not backup_id.startswith('.'), 'unsafe backup ID')
            require(isinstance(logical_dataset, str) and logical_dataset, 'missing logicalDataset')
            candidate = temp_path / backup_id
            incoming.rename(candidate)
            subprocess.run([sys.executable, str(args.manifest_tool), 'verify', '--backup-dir', str(candidate)], check=True)
            subprocess.run([sys.executable, str(args.publisher), '--published-root', str(published),
                            '--manifest-tool', str(args.manifest_tool), 'create', str(candidate)], check=True)
            subprocess.run([sys.executable, str(args.publisher), '--published-root', str(published),
                            '--manifest-tool', str(args.manifest_tool), 'verify-current'], check=True)

            current = published.resolve(strict=True)
            manifest_path = current / 'dataset-manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            require(manifest.get('backupId') == backup_id and manifest.get('logicalDataset') == logical_dataset,
                    'published identity changed after verification')
            marker = {
                'format': 1,
                'feature': '0034-FEAT/0035-FEAT',
                'state': 'verified-published',
                'snapshotEligible': True,
                'backupId': backup_id,
                'logicalDataset': logical_dataset,
                'datasetRelativePath': dataset_relative,
                'manifestSha256': sha256_file(manifest_path),
                'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                'sourceIdentity': f'{args.host}:{source}',
            }
            # A repeated, byte-identical, already accepted generation is a true
            # no-op: preserve the marker timestamp and do not disturb snapshots.
            existing_marker = None
            if args.verification_marker.is_file() and not args.verification_marker.is_symlink():
                try:
                    existing_marker = json.loads(args.verification_marker.read_text(encoding='utf-8'))
                except (ValueError, OSError):
                    pass
            identity_keys = ('format', 'feature', 'state', 'snapshotEligible',
                             'backupId', 'logicalDataset', 'datasetRelativePath',
                             'manifestSha256', 'sourceIdentity')
            already_accepted = (isinstance(existing_marker, dict) and
                                all(existing_marker.get(key) == marker[key] for key in identity_keys))
            if not already_accepted:
                atomic_marker(args.verification_marker, marker)
            print('ALREADY_VERIFIED' if already_accepted else 'VERIFIED_RECEIVE')
            print(json.dumps({
                'backupId': backup_id,
                'logicalDataset': logical_dataset,
                'state': 'verified-published',
                'snapshotEligible': True,
                'destination': str(published),
                'datasetRelativePath': dataset_relative,
                'verificationMarker': str(args.verification_marker),
            }, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
