#!/usr/bin/env python3
"""Disposable gate-4 concurrency and acceptance-identity checks."""
from pathlib import Path
import tempfile, subprocess, sys, json, hashlib, os, fcntl, time
role = Path(__file__).resolve().parents[1]
guard = role / 'files/sync/scripts/fixed-dataset-source-guard.py'
with tempfile.TemporaryDirectory() as td:
    root=Path(td); data=root/'diaries-backup'; data.mkdir()
    lock=root/'.diaries-backup-fixed.lock'; lock.touch()
    marker=root/'.diaries-backup-fixed-verified.json'
    manifest=data/'dataset-manifest.json'; manifest.write_text('{"backupId":"test-001"}\n')
    def accept():
        marker.write_text(json.dumps({'schemaVersion':1, 'root':str(data), 'backupId':'test-001', 'manifestSha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    accept()
    binpath=root/'rsync'; binpath.write_text('#!/bin/sh\nprintf "PASS-GUARD\\n"\n'); binpath.chmod(0o755)
    cmd=[sys.executable,str(guard),'--lock',str(lock),'--marker',str(marker),'--dataset',str(data),'--',str(binpath)]
    def run(): return subprocess.run(cmd,capture_output=True,text=True,timeout=6)
    assert run().returncode == 0
    marker.unlink(); assert run().returncode == 3
    accept(); manifest.write_text('{"backupId":"tampered"}\n'); assert run().returncode == 3
    manifest.write_text('{"backupId":"test-001"}\n'); accept()
    # Hold writer lock: source reader cannot complete until it releases.
    with lock.open('rb') as handle:
        fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        time.sleep(0.25)
        assert proc.poll() is None, 'reader escaped exclusive writer lock'
        fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        out,err=proc.communicate(timeout=6)
        assert proc.returncode == 0,err
    # Reader guard holds SH lock for rsync process lifetime, proving writer blocked.
    ready=root/'reader-ready'
    binpath.write_text('#!/bin/sh\ntouch '+str(ready)+'\nsleep 1\n')
    with lock.open('rb') as writer:
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        for _ in range(100):
            if ready.exists(): break
            time.sleep(0.01)
        assert ready.exists(), 'rsync reader never started'
        assert proc.poll() is None
        try:
            fcntl.flock(writer.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            raise AssertionError('writer acquired lock during active guarded rsync')
        except BlockingIOError:
            pass
        proc.communicate(timeout=6)
        assert proc.returncode == 0
        fcntl.flock(writer.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(writer.fileno(),fcntl.LOCK_UN)
print('PASS: fixed source marker/digest fail closed; writer excludes transfer; rsync excludes writer')
