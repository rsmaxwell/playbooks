#!/usr/bin/env python3
"""0036 Step 3 Gate 4: disposable SSH/rsync coordination rehearsal; run on mars.

Requires local copies of the 0034 fixture, 0036 manifest writer and source guard.
Does not touch production datasets, services, timers, or Btrfs snapshots.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


def run(cmd, *, input=None, check=True, timeout=90):
    return subprocess.run(cmd, input=input, text=True, capture_output=True,
                          check=check, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pluto', default='pluto', help='SSH host alias reachable from mars')
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--manifest-tool', type=Path, required=True)
    parser.add_argument('--guard', type=Path, required=True)
    a = parser.parse_args()
    if not a.pluto or not all(c.isalnum() or c in '.-_' for c in a.pluto):
        raise ValueError('invalid SSH alias')
    for asset in (a.fixture, a.manifest_tool, a.guard):
        if not asset.is_file():
            raise ValueError(f'missing asset: {asset}')
    for utility in ('rsync', 'ssh', 'scp'):
        if shutil.which(utility) is None:
            raise ValueError(f'{utility} required on mars')
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', a.pluto]
    remote_root = None
    with tempfile.TemporaryDirectory(prefix='diaries-0036-cross-host-') as td:
        local = Path(td)
        try:
            # The remote parent is created with mktemp, never a production directory.
            remote_root = run(ssh + ['mktemp -d -t diaries-0036-cross-host-XXXXXXXX']).stdout.strip()
            if not remote_root.startswith('/tmp/diaries-0036-cross-host-') or '\n' in remote_root:
                raise RuntimeError(f'unsafe remote rehearsal path: {remote_root!r}')
            remote_dataset = remote_root + '/diaries-backup'
            remote_guard = remote_root + '/fixed-dataset-source-guard.py'
            remote_lock = remote_root + '/.diaries-backup-fixed.lock'
            remote_marker = remote_root + '/.diaries-backup-fixed-verified.json'
            run(['scp', '-q', str(a.guard), a.pluto + ':' + remote_guard])
            spec = importlib.util.spec_from_file_location('fixture0034', a.fixture)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            candidate = module.create_candidate(local)
            dataset = local / 'diaries-backup'
            candidate.rename(dataset)
            writer = [sys.executable, str(a.manifest_tool), 'write', '--backup-dir', str(dataset),
                      '--fixed-backup-id', '20261016-120000Z', '--logical-dataset', 'common',
                      '--launch-mode', 'production', '--known-consumer', 'production',
                      '--database-storage-identity', 'disposable-db', '--database-name', 'diaries0036test',
                      '--files-selector', 'disposable-files', '--files-root', '/disposable/nas',
                      '--application-identity-json', '{"rehearsal":"0036-cross-host"}',
                      '--writer-method', 'disposable-rehearsal', '--writer', 'diaries-responder',
                      '--writer-evidence', 'synthetic quiesced', '--image-row-count', '2',
                      '--catalogued-file-count', '2', '--staging-disposition', 'empty',
                      '--staging-entry-count', '0', '--staging-note', 'excluded',
                      '--started-at', '2026-10-16T11:59:00+00:00',
                      '--completed-at', '2026-10-16T12:00:00+00:00']
            run(writer)
            run([sys.executable, str(a.manifest_tool), 'verify', '--backup-dir', str(dataset),
                 '--allow-fixed-working-root'])
            run(['rsync', '-a', str(dataset) + '/', a.pluto + ':' + remote_dataset + '/'])
            manifest_bytes = (dataset / 'dataset-manifest.json').read_bytes()
            manifest = json.loads(manifest_bytes)
            marker = {'schemaVersion': 1, 'root': remote_dataset,
                      'backupId': manifest['backupId'],
                      'manifestSha256': hashlib.sha256(manifest_bytes).hexdigest()}
            # Only write to the isolated mktemp parent and ensure the source lock exists.
            bootstrap = ('import json, pathlib, sys; p=pathlib.Path(sys.argv[1]); '
                         '(p/".diaries-backup-fixed.lock").touch(); '
                         '(p/".diaries-backup-fixed-verified.json").write_text(sys.stdin.read())')
            run(ssh + ['python3', '-c', shlex.quote(bootstrap), shlex.quote(remote_root)],
                input=json.dumps(marker) + '\n')
            guard_cmd = ('python3 ' + shlex.quote(remote_guard) +
                         ' --lock ' + shlex.quote(remote_lock) +
                         ' --marker ' + shlex.quote(remote_marker) +
                         ' --dataset ' + shlex.quote(remote_dataset) + ' -- rsync')
            dest = local / 'incoming'; dest.mkdir()
            pull = ['rsync', '-a', '--delete', '--rsync-path=' + guard_cmd,
                    a.pluto + ':' + remote_dataset + '/', str(dest) + '/']
            run(pull)
            # The receiver is a disposable named backup-id tree for strict schema-2 verification.
            verified = local / manifest['backupId']
            dest.rename(verified)
            run([sys.executable, str(a.manifest_tool), 'verify', '--backup-dir', str(verified)])
            print('PASS: guarded SSH/rsync transferred and independently verified disposable schema-2 dataset')
            # Missing marker must block; no destination modifications.
            run(ssh + ['rm', '-f', shlex.quote(remote_marker)])
            blocked = run(pull, check=False)
            if blocked.returncode == 0 or 'BLOCKED:' not in blocked.stderr:
                raise AssertionError('missing acceptance marker did not fail closed: ' + blocked.stderr)
            print('PASS: missing acceptance marker prevents guarded cross-host pull')
            run(ssh + ['python3', '-c', shlex.quote(bootstrap), shlex.quote(remote_root)],
                input=json.dumps(marker) + '\n')
            # Exclusive remote writer lock must prevent the reader from starting.
            holder_script = ('import fcntl,pathlib,sys,time; '
                             'f=pathlib.Path(sys.argv[1]).open("rb"); '
                             'fcntl.flock(f,fcntl.LOCK_EX); print("LOCKED",flush=True); time.sleep(4)')
            holder = subprocess.Popen(ssh + ['python3', '-u', '-c', shlex.quote(holder_script),
                                             shlex.quote(remote_lock)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                if holder.stdout.readline().strip() != 'LOCKED':
                    raise AssertionError('remote exclusive lock not acquired')
                try:
                    run(pull, timeout=1.5)
                    raise AssertionError('guarded reader succeeded during writer lock')
                except subprocess.TimeoutExpired:
                    pass
            finally:
                holder.wait(timeout=10)
                holder.stdout.close(); holder.stderr.close()
            print('PASS: remote exclusive capture lock prevents concurrent SSH/rsync reader')
            # Previous verified receiving copy remains intact after blocked attempts.
            run([sys.executable, str(a.manifest_tool), 'verify', '--backup-dir', str(verified)])
            print('PASS: previously received verified copy remains intact after rejected transfers')
        finally:
            if remote_root and remote_root.startswith('/tmp/diaries-0036-cross-host-'):
                run(ssh + ['rm', '-rf', '--', shlex.quote(remote_root)], check=False)
    print('PASS: 0036 Gate 4 disposable cross-host rehearsal; all temporary paths cleaned')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, AssertionError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        sys.exit(1)
