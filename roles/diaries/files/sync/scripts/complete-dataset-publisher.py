#!/usr/bin/env python3
"""0034 Step 5: isolated, opt-in publisher of existing verified schema-2 datasets.

Does not capture data, run rsync, modify legacy repositories, or run in deployment.
"""
import argparse
from contextlib import nullcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid


def die(message):
    raise RuntimeError(message)


def validate_layout(root):
    root = Path(root).absolute()
    if root.name != 'diaries-backup':
        die('published path must have basename diaries-backup')
    parent = root.parent
    if not parent.is_dir() or parent.is_symlink():
        die('published parent must be an existing real directory')
    store = parent / '.diaries-backup-generations'
    lock = parent / '.diaries-backup.lock'
    if root.exists() and not root.is_symlink():
        die('refusing to replace an existing real published directory')
    if store.is_symlink():
        die('refusing symlink generation store')
    return root, store, lock


def validate_generation(source, manifest_tool):
    if source.is_symlink() or not source.is_dir() or source.name.startswith('.'):
        die('candidate must be a completed real directory')
    manifest_path = source / 'dataset-manifest.json'
    if manifest_path.is_symlink():
        die('manifest symlink refused')
    doc = json.loads(manifest_path.read_text())
    backup_id = doc.get('backupId')
    if backup_id != source.name:
        die('candidate directory must equal manifest backupId')
    cmd = [sys.executable, str(manifest_tool), 'verify', '--backup-dir', str(source)]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return backup_id


def manifest_digest(directory):
    manifest = directory / 'dataset-manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        die('manifest missing or unsafe')
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def validate_existing_identity(source, destination, root, store, manifest_tool, backup_id):
    # Never overwrite a historical generation or silently roll back the pointer.
    if destination.is_symlink() or not destination.is_dir():
        die('existing generation path is unsafe')
    existing_id = validate_generation(destination, manifest_tool)
    if existing_id != backup_id or manifest_digest(source) != manifest_digest(destination):
        die('backup ID conflict: existing generation manifest differs')
    if not root.is_symlink() or current(root, store) != destination.resolve(strict=True):
        die('backup ID already exists but is not the currently published generation')
    print(f'ALREADY_PUBLISHED {backup_id}')


def current(root, store):
    if not root.is_symlink():
        die('no published generation')
    link = os.readlink(root)
    target = (root.parent / link).resolve(strict=True)
    if target.parent != store.resolve() or not target.is_dir() or target.name.startswith('.'):
        die('published pointer escapes generation store')
    return target


def fsync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def copy_candidate(source, staging, *, link_files=False):
    """Copy verified media, optionally sharing immutable source file inodes.

    Linked mode is opt-in because callers must preserve the source as immutable
    until the linked generation is retired. Never link from a mutable live tree.
    All directory entries are scanned with lstat to reject symlinks/devices.
    """
    def safe_tree(path):
        for base, dirs, files in os.walk(path, followlinks=False):
            for name in dirs + files:
                entry = Path(base) / name
                mode = entry.lstat().st_mode
                if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    die(f'unsafe candidate entry: {entry}')
                if stat.S_ISDIR(mode) and entry.is_symlink():
                    die('candidate contains symbolic link')
    safe_tree(source)
    if not link_files:
        shutil.copytree(source, staging, symlinks=False)
        return
    if source.stat().st_dev != staging.parent.stat().st_dev:
        die('linked candidate requires same filesystem as generation store')
    def materialize(src, dst):
        dst.mkdir(mode=src.stat().st_mode & 0o777)
        for entry in src.iterdir():
            target = dst / entry.name
            mode = entry.lstat().st_mode
            if stat.S_ISDIR(mode):
                materialize(entry, target)
            elif stat.S_ISREG(mode):
                # Link only the large immutable Files payload; metadata and DB
                # receive separate inodes so they remain independently auditable.
                if 'files' in entry.relative_to(source).parts[:1]:
                    os.link(entry, target, follow_symlinks=False)
                else:
                    shutil.copy2(entry, target, follow_symlinks=False)
            else:
                die(f'unsafe candidate entry: {entry}')
    materialize(source, staging)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--published-root', type=Path, required=True)
    parser.add_argument('--held-lock-fd', type=int, default=None, help='0036: inherited transaction lock FD (internal use)')
    parser.add_argument('--manifest-tool', type=Path, default=Path(__file__).with_name('complete-dataset-manifest.py'))
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('preflight')
    create = sub.add_parser('create'); create.add_argument('candidate', type=Path)
    linked = sub.add_parser('create-linked'); linked.add_argument('candidate', type=Path)
    sub.add_parser('verify-current'); sub.add_parser('show-current-id')
    pin = sub.add_parser('pin-run'); pin.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root, store, lock_path = validate_layout(args.published_root)
    if args.action == 'preflight':
        if store.exists() and not store.is_dir(): die('invalid generation store')
        if root.is_symlink():
            current(root, store)
        print('PREFLIGHT OK: no capture or publication performed'); return
    # A 0036 orchestrator may hold this exact lock continuously across capture,
    # publication and verification. Inherited FD prevents recursive flock deadlock.
    if args.held_lock_fd is not None:
        fd = args.held_lock_fd
        if fd < 3 or os.fstat(fd).st_ino != lock_path.stat().st_ino or os.fstat(fd).st_dev != lock_path.stat().st_dev:
            die('inherited lock FD does not match publisher lock')
        lock_context = nullcontext(fd)
    else:
        lock_context = open(lock_path, 'a+b')
    with lock_context as lock:
        if args.held_lock_fd is None:
            fcntl.flock(lock, fcntl.LOCK_EX if args.action in ('create', 'create-linked') else fcntl.LOCK_SH)
        if args.action in ('create', 'create-linked'):
            source = args.candidate.resolve(strict=True)
            if source == root or source == root.parent or store in source.parents:
                die('candidate overlaps publication directory')
            backup_id = validate_generation(source, args.manifest_tool)
            store.mkdir(mode=0o700, exist_ok=True)
            if store.stat().st_dev != root.parent.stat().st_dev:
                die('generation store must share filesystem with published pointer')
            destination = store / backup_id
            if destination.exists() or destination.is_symlink():
                validate_existing_identity(source, destination, root, store, args.manifest_tool, backup_id)
                return 0
            staging_parent = store / ('.staging-' + uuid.uuid4().hex)
            staging = staging_parent / backup_id
            temp_link = root.parent / ('.diaries-backup-link.' + uuid.uuid4().hex)
            try:
                staging_parent.mkdir(mode=0o700)
                copy_candidate(source, staging, link_files=(args.action == 'create-linked'))
                validate_generation(staging, args.manifest_tool)
                os.replace(staging, destination)
                fsync_directory(store)
                os.symlink(os.path.relpath(destination, root.parent), temp_link)
                os.replace(temp_link, root)
                fsync_directory(root.parent)
                print(f'PUBLISHED {backup_id}')
            finally:
                if temp_link.is_symlink(): temp_link.unlink()
                if staging_parent.exists(): shutil.rmtree(staging_parent)
        elif args.action in ('verify-current', 'show-current-id', 'pin-run'):
            selected = current(root, store)
            backup_id = validate_generation(selected, args.manifest_tool)
            if args.action == 'verify-current': print(f'VERIFIED {backup_id}')
            elif args.action == 'show-current-id': print(backup_id)
            else:
                if not args.command: die('pin-run requires a command')
                command = args.command[1:] if args.command[0] == '--' else args.command
                if not command: die('pin-run requires a command')
                # Environment permits the receiving script to use the pinned immutable path.
                env = os.environ.copy(); env['DIARIES_PINNED_GENERATION'] = str(selected); env['DIARIES_PINNED_BACKUP_ID'] = backup_id
                return subprocess.call(command, env=env)
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr); sys.exit(1)
