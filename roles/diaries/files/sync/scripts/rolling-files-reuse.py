#!/usr/bin/env python3
"""0036 opt-in deduplication of a private captured Files candidate.

Only hard-links identical immutable regular files to a verified previous generation.
This never writes to existing inodes. Must run before writing the candidate manifest.
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.digest()


def reuse(candidate, previous, manifest_tool):
    candidate = Path(candidate).absolute()
    previous = Path(previous).absolute()
    if candidate.is_symlink() or previous.is_symlink() or not candidate.is_dir() or not previous.is_dir():
        raise RuntimeError('candidate and previous must be real directories')
    if candidate == previous or candidate in previous.parents or previous in candidate.parents:
        raise RuntimeError('candidate and previous overlap')
    subprocess.run([sys.executable, str(manifest_tool), 'verify', '--backup-dir', str(previous)],
                   check=True, capture_output=True)
    source = candidate / 'files'
    reference = previous / 'files'
    if source.is_symlink() or reference.is_symlink() or not source.is_dir() or not reference.is_dir():
        raise RuntimeError('unsafe Files root')
    if source.stat().st_dev != reference.stat().st_dev:
        raise RuntimeError('hard-link reuse requires same filesystem')
    linked = 0
    bytes_saved = 0
    for base, dirs, files in os.walk(source, followlinks=False):
        directory = Path(base)
        for name in dirs:
            if not stat.S_ISDIR((directory / name).lstat().st_mode):
                raise RuntimeError('unsafe candidate directory')
        for name in files:
            target = directory / name
            s = target.lstat()
            if not stat.S_ISREG(s.st_mode):
                raise RuntimeError('unsafe candidate file')
            relative = target.relative_to(source)
            old = reference / relative
            try:
                o = old.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(o.st_mode):
                continue
            if (s.st_size, stat.S_IMODE(s.st_mode), s.st_uid, s.st_gid, s.st_mtime_ns) != (o.st_size, stat.S_IMODE(o.st_mode), o.st_uid, o.st_gid, o.st_mtime_ns):
                continue
            if sha(target) != sha(old):
                continue
            temp = target.with_name('.0036-link-' + uuid.uuid4().hex)
            try:
                os.link(old, temp, follow_symlinks=False)
                os.replace(temp, target)
            finally:
                if temp.exists():
                    temp.unlink()
            linked += 1
            bytes_saved += s.st_size
    print(f'REUSED files={linked} logical_bytes={bytes_saved}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--candidate', type=Path, required=True)
    ap.add_argument('--previous', type=Path, required=True)
    ap.add_argument('--manifest-tool', type=Path, default=Path(__file__).with_name('complete-dataset-manifest.py'))
    a = ap.parse_args()
    try:
        reuse(a.candidate, a.previous, a.manifest_tool)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)
