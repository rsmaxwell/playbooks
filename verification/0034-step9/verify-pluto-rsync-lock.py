#!/usr/bin/env python3
"""0034 Step 9 live pluto proof: an in-flight rsync pins one generation.

The script is intentionally verification-only. It reads the current stable
publication into a disposable local scratch tree while holding the same shared
flock used by the mars pull contract, then attempts to publish a second already-
completed legacy backup. The publisher must block until rsync finishes; the
received tree must verify as the old backup ID; only then may the new candidate
become current.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


def die(message: str) -> None:
    raise RuntimeError(message)


def run(argv: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def output(argv: list[str]) -> str:
    return run(argv, capture=True).stdout.strip()


def tree_bytes(root: Path) -> int:
    total = 0
    for base, dirs, files in os.walk(root, followlinks=False):
        base_path = Path(base)
        for name in dirs + files:
            path = base_path / name
            if path.is_symlink():
                die(f'published generation unexpectedly contains symlink: {path}')
        for name in files:
            total += (base_path / name).stat().st_size
    return total


def publisher_cmd(publisher: Path, published_root: Path, manifest_tool: Path, *args: str) -> list[str]:
    return [sys.executable, str(publisher), '--published-root', str(published_root),
            '--manifest-tool', str(manifest_tool), *args]


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--published-root', type=Path, required=True)
    cli.add_argument('--candidate', type=Path, required=True,
                     help='second completed legacy schema-2 backup, not yet published')
    cli.add_argument('--publisher', type=Path, required=True)
    cli.add_argument('--manifest-tool', type=Path, required=True)
    cli.add_argument('--scratch-parent', type=Path, required=True)
    cli.add_argument('--bwlimit-kib', type=int, default=0,
                     help='rsync KiB/s; 0 chooses a rate intended to keep the transfer in flight for ~5 seconds')
    args = cli.parse_args()

    for path in (args.published_root, args.candidate, args.publisher,
                 args.manifest_tool, args.scratch_parent):
        if not path.is_absolute():
            die(f'absolute path required: {path}')
    if not args.publisher.is_file() or not args.manifest_tool.is_file():
        die('publisher or manifest tool missing')
    if not args.scratch_parent.is_dir() or args.scratch_parent.is_symlink():
        die('scratch parent must be an existing real directory')
    if not args.candidate.is_dir() or args.candidate.is_symlink():
        die('candidate must be a completed real directory')

    first_id = output(publisher_cmd(args.publisher, args.published_root, args.manifest_tool, 'show-current-id'))
    run(publisher_cmd(args.publisher, args.published_root, args.manifest_tool, 'verify-current'))
    first_generation = args.published_root.resolve(strict=True)
    if first_generation.name != first_id:
        die(f'current pointer/id mismatch: pointer={first_generation.name} reported={first_id}')

    candidate_manifest = json.loads((args.candidate / 'dataset-manifest.json').read_text())
    second_id = candidate_manifest.get('backupId')
    if not isinstance(second_id, str) or second_id != args.candidate.name:
        die('candidate directory does not match its manifest backupId')
    if second_id == first_id:
        die('candidate must have a new backupId distinct from current')
    run([sys.executable, str(args.manifest_tool), 'verify', '--backup-dir', str(args.candidate)])

    generation_store = args.published_root.parent / '.diaries-backup-generations'
    if (generation_store / second_id).exists():
        die(f'candidate {second_id} is already present in the generation store; use a fresh second backup')
    lock_path = args.published_root.parent / '.diaries-backup.lock'
    if not lock_path.exists():
        die(f'publisher lock missing: {lock_path}')

    total = tree_bytes(first_generation)
    if total <= 0:
        die('current published generation is unexpectedly empty')
    bwlimit = args.bwlimit_kib if args.bwlimit_kib > 0 else max(1, (total // 1024) // 5)

    scratch = Path(tempfile.mkdtemp(prefix='.0034-step9-rsync-', dir=args.scratch_parent))
    received = scratch / first_id
    received.mkdir()
    marker = scratch / 'reader-lock-held'
    reader_stdout = scratch / 'reader.stdout'
    reader_stderr = scratch / 'reader.stderr'
    writer_stdout = scratch / 'writer.stdout'
    writer_stderr = scratch / 'writer.stderr'

    print('0034 Step 9 pluto rsync/publication contention proof')
    print(f'  Current backup ID:  {first_id}')
    print(f'  Candidate backup ID:{second_id}')
    print(f'  Stable path:        {args.published_root}')
    print(f'  Current generation: {first_generation}')
    print(f'  Scratch:            {scratch}')
    print(f'  Current bytes:      {total}')
    print(f'  rsync bwlimit KiB/s:{bwlimit}')

    reader = writer = None
    try:
        shell = (
            f"printf '%s\\n' locked > {shlex.quote(str(marker))}; "
            f"exec rsync -a --delete --bwlimit={bwlimit} -- "
            f"{shlex.quote(str(args.published_root) + '/')} {shlex.quote(str(received) + '/')}"
        )
        with reader_stdout.open('w') as rout, reader_stderr.open('w') as rerr:
            reader = subprocess.Popen(['flock', '-s', str(lock_path), 'bash', '-c', shell],
                                      text=True, stdout=rout, stderr=rerr)
            deadline = time.monotonic() + 10
            while not marker.exists():
                if reader.poll() is not None:
                    die(f'rsync reader exited before acquiring the shared lock; see {reader_stderr}')
                if time.monotonic() >= deadline:
                    die('timed out waiting for rsync reader to acquire shared lock')
                time.sleep(0.05)

            with writer_stdout.open('w') as wout, writer_stderr.open('w') as werr:
                writer = subprocess.Popen(
                    publisher_cmd(args.publisher, args.published_root, args.manifest_tool,
                                  'create', str(args.candidate)),
                    text=True, stdout=wout, stderr=werr,
                )
                time.sleep(0.5)
                if reader.poll() is not None:
                    die('rsync completed too quickly to prove concurrent publication blocking; rerun with a lower --bwlimit-kib')
                if writer.poll() is not None:
                    die('publisher was not blocked by the in-flight rsync shared lock')
                if args.published_root.resolve(strict=True).name != first_id:
                    die('stable publication changed while rsync still held the shared lock')
                print('PASS: publisher remained blocked while rsync held the shared lock')

                reader_rc = reader.wait(timeout=1800)
                if reader_rc != 0:
                    die(f'rsync reader failed with exit {reader_rc}; see {reader_stderr}')
                writer_rc = writer.wait(timeout=1800)
                if writer_rc != 0:
                    die(f'publisher failed with exit {writer_rc}; see {writer_stderr}')

        run([sys.executable, str(args.manifest_tool), 'verify', '--backup-dir', str(received)])
        received_manifest = json.loads((received / 'dataset-manifest.json').read_text())
        if received_manifest.get('backupId') != first_id:
            die('received rsync tree mixed generations or has the wrong backupId')
        print(f'PASS: rsync received one coherent generation: {first_id}')

        current_id = output(publisher_cmd(args.publisher, args.published_root, args.manifest_tool, 'show-current-id'))
        run(publisher_cmd(args.publisher, args.published_root, args.manifest_tool, 'verify-current'))
        if current_id != second_id:
            die(f'publisher did not advance to second candidate: expected {second_id}, got {current_id}')
        if not (generation_store / first_id).is_dir():
            die('previous generation disappeared after publication')
        print(f'PASS: publication advanced only after rsync completion: {second_id}')
        print(f'PASS: previous generation retained: {first_id}')
        shutil.rmtree(scratch)
        print('PASS: disposable rsync scratch removed')
        print('PASS: 0034 Step 9 live rsync/publication contention proof')
        return 0
    except Exception:
        if reader is not None and reader.poll() is None:
            reader.terminate()
        if writer is not None and writer.poll() is None:
            # Once the reader is terminated the writer may legitimately acquire
            # the lock. Do not kill an active publisher mid-copy; wait for it.
            try:
                writer.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                die(f'publisher did not exit after verification failure; inspect {writer_stderr} and {scratch}')
        print(f'ERROR: verification scratch retained for inspection: {scratch}', file=sys.stderr)
        raise


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
