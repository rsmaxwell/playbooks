#!/usr/bin/env python3
"""Fast isolated regression for 0036 opt-in Files inode reuse."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

script = Path(__file__).resolve().parents[1] / 'files/sync/scripts/rolling-files-reuse.py'
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    previous = root / 'previous'
    candidate = root / 'candidate'
    for folder in (previous / 'files', candidate / 'files'):
        folder.mkdir(parents=True)
    old = previous / 'files' / 'unchanged.bin'
    new = candidate / 'files' / 'unchanged.bin'
    old.write_bytes(b'A' * 8192)
    new.write_bytes(old.read_bytes())
    os.utime(new, ns=(old.stat().st_atime_ns, old.stat().st_mtime_ns))
    (previous / 'files' / 'modified.bin').write_bytes(b'older')
    (candidate / 'files' / 'modified.bin').write_bytes(b'newer')
    (candidate / 'files' / 'additional.bin').write_bytes(b'added')
    (previous / 'files' / 'deleted.bin').write_bytes(b'deleted')
    verify = root / 'verify.py'
    verify.write_text('import sys; sys.exit(0)\n')  # only simulates trusted prior manifest verification
    run = subprocess.run([sys.executable, str(script), '--candidate', str(candidate),
                          '--previous', str(previous), '--manifest-tool', str(verify)],
                         capture_output=True, text=True, check=True)
    assert 'REUSED files=1 ' in run.stdout, run.stdout
    assert old.stat().st_ino == new.stat().st_ino
    assert (candidate / 'files' / 'modified.bin').read_bytes() == b'newer'
    assert not (candidate / 'files' / 'deleted.bin').exists()
    assert (candidate / 'files' / 'additional.bin').is_file()
    assert (previous / 'files' / 'modified.bin').read_bytes() == b'older'
    # Do not allow candidate symlinks; even nonmatching names must be rejected.
    (candidate / 'files' / 'link').symlink_to(old)
    bad = subprocess.run([sys.executable, str(script), '--candidate', str(candidate),
                          '--previous', str(previous), '--manifest-tool', str(verify)],
                         capture_output=True, text=True)
    assert bad.returncode != 0 and 'unsafe candidate file' in bad.stderr
print('PASS: 0036 candidate inode reuse, change/add/delete, source immutability and symlink rejection')
