#!/usr/bin/env python3
"""Prove two unchanged Btrfs snapshot files share at least one physical extent."""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys

EXTENT_RE = re.compile(r'^\s*\d+:\s+\d+\.\.\s*\d+:\s+(\d+)\.\.\s*(\d+):')


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def extents(path: Path) -> tuple[list[tuple[int, int]], str]:
    result = subprocess.run(['filefrag', '-v', '-e', str(path)], text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f'filefrag failed for {path}: {result.stderr.strip()}')
    values = []
    for line in result.stdout.splitlines():
        match = EXTENT_RE.match(line)
        if match:
            values.append((int(match.group(1)), int(match.group(2))))
    if not values:
        raise RuntimeError(f'no physical extents parsed for {path}; filefrag output:\n{result.stdout}')
    return values, result.stdout


def overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return max(a[0], b[0]) <= min(a[1], b[1])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('first', type=Path)
    p.add_argument('second', type=Path)
    args = p.parse_args()
    for path in (args.first, args.second):
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f'expected real regular file: {path}')
    if args.first.stat().st_size != args.second.stat().st_size:
        raise RuntimeError('files differ in size; choose an unchanged file present in both snapshots')
    first_hash = sha256(args.first)
    second_hash = sha256(args.second)
    if first_hash != second_hash:
        raise RuntimeError('files differ in SHA-256; choose an unchanged file present in both snapshots')
    first, out1 = extents(args.first)
    second, out2 = extents(args.second)
    shared = [(a, b) for a in first for b in second if overlaps(a, b)]
    print(f'first={args.first}')
    print(f'second={args.second}')
    print(f'bytes={args.first.stat().st_size};sha256={first_hash}')
    print(f'first_extents={len(first)};second_extents={len(second)};shared_physical_ranges={len(shared)}')
    if not shared:
        print('FIRST filefrag:\n' + out1)
        print('SECOND filefrag:\n' + out2)
        raise RuntimeError('no shared physical extent detected')
    print(f'PASS: unchanged files share Btrfs physical extent(s); example={shared[0]}')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(2)
