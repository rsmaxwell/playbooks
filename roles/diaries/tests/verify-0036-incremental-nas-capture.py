#!/usr/bin/env python3
"""Disposable host-side regression of 0036 rsync/link-dest capture semantics.

Does not require Docker/NAS; production maintenance-image availability and
orchestrator integration must be checked separately on pluto.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

if not shutil.which('rsync'):
    raise SystemExit('SKIP: rsync not installed on regression host')

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    live, previous, candidate = (root / x for x in ('live', 'previous', 'candidate'))
    for d in (live, previous / 'files', candidate / 'files'):
        d.mkdir(parents=True)
    (live / 'same.bin').write_bytes(b'A' * 4096)
    (live / 'changed.bin').write_bytes(b'updated')
    (live / 'added.bin').write_bytes(b'new')
    (live / '.image-staging').mkdir()
    (live / '.image-staging' / 'lock').write_text('exclude')
    (previous / 'files' / 'same.bin').write_bytes((live / 'same.bin').read_bytes())
    (previous / 'files' / 'changed.bin').write_bytes(b'original')
    (previous / 'files' / 'removed.bin').write_bytes(b'obsolete')
    shutil.copystat(live / 'same.bin', previous / 'files' / 'same.bin')
    original_inode = (previous / 'files' / 'same.bin').stat().st_ino
    previous_bytes = {p.name: p.read_bytes() for p in (previous / 'files').iterdir()}
    uid, gid = os.getuid(), os.getgid()
    common = ['-rptcog', f'--chown={uid}:{gid}', '--exclude=/.image-staging/']
    subprocess.run(['rsync', *common, f'--link-dest={previous / "files"}/', f'{live}/', f'{candidate / "files"}/'], check=True)
    assert (candidate / 'files' / 'same.bin').stat().st_ino == original_inode, 'unchanged file not linked'
    assert (candidate / 'files' / 'changed.bin').read_bytes() == b'updated'
    assert (candidate / 'files' / 'changed.bin').stat().st_ino != (previous / 'files' / 'changed.bin').stat().st_ino
    assert (candidate / 'files' / 'added.bin').read_bytes() == b'new'
    assert not (candidate / 'files' / 'removed.bin').exists()
    assert not (candidate / 'files' / '.image-staging').exists()
    assert {p.name: p.read_bytes() for p in (previous / 'files').iterdir()} == previous_bytes
    check = subprocess.run(['rsync', '-rptcogni', f'--chown={uid}:{gid}', '--delete', '--exclude=/.image-staging/', f'{live}/', f'{candidate / "files"}/'], capture_output=True, text=True, check=True)
    assert not check.stdout.strip(), check.stdout
    # A post-transfer source change is detected, even with restored timestamp/size.
    item = live / 'same.bin'
    old_stat = item.stat()
    item.write_bytes(b'B' * 4096)
    os.utime(item, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    check = subprocess.run(['rsync', '-rptcogni', f'--chown={uid}:{gid}', '--delete', '--exclude=/.image-staging/', f'{live}/', f'{candidate / "files"}/'], capture_output=True, text=True, check=True)
    assert check.stdout.strip(), 'changed NAS data not detected'
    assert (candidate / 'files' / 'same.bin').read_bytes() == b'A' * 4096
    assert (previous / 'files' / 'same.bin').read_bytes() == b'A' * 4096
    # Interrupted candidate is discarded without touching existing generation.
    shutil.rmtree(candidate)
    assert {p.name: p.read_bytes() for p in (previous / 'files').iterdir()} == previous_bytes
print('PASS: 0036 rsync changed/add/delete, inode reuse, checksum drift detection, exclusion and failure isolation')
