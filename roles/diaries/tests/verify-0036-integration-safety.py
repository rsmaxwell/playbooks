#!/usr/bin/env python3
"""0036 source-contract and disposable flock lifetime regression."""
import fcntl
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

scripts = Path(__file__).resolve().parents[1] / 'files/sync/scripts'
source = (scripts / 'production-complete-dataset.py').read_text()
required = [
    'DIARIES_0036_ROLLING_ENABLED', 'DIARIES_0036_INCREMENTAL_NAS_ENABLED',
    'incremental_capture_preflight()', 'incremental_capture_files(partial, prior_incremental)',
    '"/previous", True', 'rsync -rptcogni',
    'with incremental_generation_transaction(p) as held_fd:',
    'incremental=True, held_lock_fd=held_fd',
    'publish_completed_backup(p, backup, rolling=rolling, held_lock_fd=held_fd)',
    'run(publisher_argv(p, "verify-current", held_lock_fd=held_lock_fd)',
]
missing = [s for s in required if s not in source]
if missing:
    sys.exit('FAIL: missing integration elements: ' + repr(missing))
spec = importlib.util.spec_from_file_location('production_complete_dataset', scripts / 'production-complete-dataset.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix='0036-lock-') as d:
    root = Path(d) / 'diaries-backup'
    class FakeProduction:
        published_root = root
        publisher_tool = scripts / "complete-dataset-publisher.py"
        manifest_tool = scripts / "complete-dataset-manifest.py"
    # Parent owns the publisher lock and keeps it through its work.
    with module.incremental_generation_transaction(FakeProduction()) as fd:
        lock = root.parent / '.diaries-backup.lock'
        assert os.fstat(fd).st_ino == lock.stat().st_ino
        contender = subprocess.run([
            sys.executable, '-c',
            'import fcntl,sys; f=open(sys.argv[1],"a+b"); '
            'fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)', str(lock),
        ], capture_output=True)
        assert contender.returncode != 0, 'concurrent cleanup/publisher acquired lock'
        # Publisher must accept inherited FD without recursively acquiring flock.
        proc = subprocess.run(module.publisher_argv(FakeProduction(), 'verify-current', held_lock_fd=fd),
                              capture_output=True, text=True, pass_fds=(fd,), timeout=10)
        assert proc.returncode != 0 and 'no published generation' in proc.stderr, proc.stderr
    contender = subprocess.run([
        sys.executable, '-c',
        'import fcntl,sys; f=open(sys.argv[1],"a+b"); '
        'fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)', str(lock),
    ], capture_output=True)
    assert contender.returncode == 0, 'transaction lock leaked after completion'
print('PASS: 0036 transaction lock blocks concurrent publisher/cleanup across capture and releases afterwards')
print('PASS: inherited publisher FD prevents recursive-lock deadlock')
