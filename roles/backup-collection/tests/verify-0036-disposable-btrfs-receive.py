#!/usr/bin/env python3
"""Disposable real Btrfs + SSH fixed receive rehearsal. Run as richard on mars.

Requires a *dedicated empty test parent* on a Btrfs filesystem, supplied explicitly.
No automatic sudo, no production paths, no timers, no replication, no deletion of existing paths.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid


def run(cmd, *, check=True, timeout=150, input=None):
    return subprocess.run(cmd, check=check, timeout=timeout, input=input, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def expect(ok, reason):
    if not ok: raise RuntimeError(reason)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--btrfs-test-parent', type=Path, required=True,
                    help='existing dedicated, empty, writable Btrfs test directory on mars')
    ap.add_argument('--pluto', default='pluto')
    ap.add_argument('--fixture', type=Path, required=True)
    ap.add_argument('--manifest-tool', type=Path, required=True)
    ap.add_argument('--guard', type=Path, required=True)
    ap.add_argument('--receiver', type=Path, required=True)
    ap.add_argument('--publisher', type=Path, required=True)
    a=ap.parse_args()
    for file in (a.fixture,a.manifest_tool,a.guard,a.receiver,a.publisher):
        expect(file.is_file(), f'missing prerequisite: {file}')
    expect(a.pluto and all(c.isalnum() or c in '._-' for c in a.pluto), 'unsafe SSH alias')
    parent=a.btrfs_test_parent
    expect(parent.is_absolute() and parent.is_dir() and not parent.is_symlink(), 'test parent must exist, absolute and not a symlink')
    parent=parent.resolve(strict=True)
    expect(str(parent) not in ('/', '/tmp', '/mnt', '/home', '/home/richard'), 'unsafe broad test parent')
    expect('0036' in parent.name or 'rehearsal' in parent.name, 'test parent must be explicitly named rehearsal or 0036')
    expect(not any(parent.iterdir()), 'test parent must be empty before run')
    expect(os.access(parent, os.W_OK|os.X_OK), 'test parent must be writable by invoking user')
    expect(run(['findmnt','-n','-T',str(parent),'-o','FSTYPE']).stdout.strip()=='btrfs', 'test parent is not on Btrfs')
    for exe in ('btrfs','rsync','ssh','scp'):
        expect(shutil.which(exe), f'{exe} not installed')
    ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10',a.pluto]
    run(ssh+['true'])
    root=parent/('disposable-'+uuid.uuid4().hex[:12]); snapshot=parent/(root.name+'-snapshot')
    remote=None
    local_source=parent/(root.name+'-source-fixture')
    created=[]
    try:
        run(['btrfs','subvolume','create',str(root)]); created.append(root)
        (root/'backup/pluto').mkdir(parents=True)
        (root/'backup').mkdir(exist_ok=True)
        marker=root/'backup/.diaries-snapshot-verified.json'
        lock=root/'backup/.btrfs-snapshot-writer.lock'
        lock.touch()
        remote=run(ssh+['mktemp -d -t diaries-0036-btrfs-XXXXXXXX']).stdout.strip()
        expect(remote.startswith('/tmp/diaries-0036-btrfs-') and '\n' not in remote, 'unsafe remote disposable path')
        remote_source=remote+'/diaries-backup'
        remote_guard=remote+'/fixed-dataset-source-guard.py'
        run(['scp','-q',str(a.guard),a.pluto+':'+remote_guard])
        spec=importlib.util.spec_from_file_location('fixture0036',a.fixture)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        local_source.mkdir()
        candidate=module.create_candidate(local_source)
        source=local_source/'diaries-backup';candidate.rename(source)
        def write_manifest(backup_id):
            cmd=[sys.executable,str(a.manifest_tool),'write','--backup-dir',str(source),
                 '--fixed-backup-id',backup_id,'--logical-dataset','common',
                 '--launch-mode','production','--known-consumer','production',
                 '--database-storage-identity','rehearsal-db','--database-name','diaries0036',
                 '--files-selector','rehearsal-files','--files-root','/disposable/nas',
                 '--application-identity-json','{"rehearsal":"0036-btrfs"}',
                 '--writer-method','disposable-rehearsal','--writer','diaries-responder',
                 '--writer-evidence','synthetic quiesced','--image-row-count','2',
                 '--catalogued-file-count','2','--staging-disposition','empty',
                 '--staging-entry-count','0','--staging-note','excluded',
                 '--started-at','2026-10-16T12:00:00+00:00',
                 '--completed-at','2026-10-16T12:01:00+00:00']
            run(cmd)
            run([sys.executable,str(a.manifest_tool),'verify','--backup-dir',str(source),'--allow-fixed-working-root'])
        def publish_source():
            run(['rsync','-a','--delete',str(source)+'/',a.pluto+':'+remote_source+'/'])
            doc=json.loads((source/'dataset-manifest.json').read_text())
            mark={'schemaVersion':1,'root':remote_source,'backupId':doc['backupId'],
                  'manifestSha256':hashlib.sha256((source/'dataset-manifest.json').read_bytes()).hexdigest()}
            boot=('import pathlib,sys; p=pathlib.Path(sys.argv[1]); '
                  '(p/".diaries-backup-fixed.lock").touch(); '
                  '(p/".diaries-backup-fixed-verified.json").write_text(sys.stdin.read())')
            run(ssh+['python3','-c',shlex.quote(boot),shlex.quote(remote)],input=json.dumps(mark)+'\n')
        def receive(success=True):
            cmd=[sys.executable,str(a.receiver),'--fixed-destination',
                '--host',a.pluto,'--source-parent',remote,
                '--destination-parent',str(root/'backup/pluto'),
                '--snapshot-source-root',str(root),'--verification-marker',str(marker),
                '--repository-lock',str(lock),'--publisher',str(a.publisher),
                '--manifest-tool',str(a.manifest_tool),'--fixed-source-guard',remote_guard]
            return run(cmd,check=success)
        write_manifest('20261016-120100Z');publish_source();receive()
        expect(json.loads(marker.read_text())['snapshotEligible'], 'initial marker not eligible')
        working=root/'backup/pluto/diaries-backup'
        expect((working/'files/a.txt').read_text()=='alpha\n','initial receive incorrect')
        print('PASS: initial guarded transfer into disposable Btrfs working subvolume')
        run(['btrfs','subvolume','snapshot','-r',str(root),str(snapshot)]);created.append(snapshot)
        expect((snapshot/'backup/pluto/diaries-backup/files/a.txt').read_text()=='alpha\n','snapshot invalid')
        print('PASS: read-only Btrfs snapshot created and retained')
        # Update fixture inventory, hashes and manifest using real fixture generation on the same root.
        (source/'files/a.txt').write_text('alpha changed\n')
        (source/'files/new.txt').write_text('added\n')
        (source/'files/nested/b.bin').unlink()
        entries=[]
        for f in sorted((source/'files').rglob('*')):
            if f.is_file():
                entries.append({'path':f.relative_to(source).as_posix(),'sizeBytes':f.stat().st_size,
                                'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
        (source/'verification/inventory.json').write_text(json.dumps({'schemaVersion':1,'root':'files','fileCount':len(entries),
              'totalBytes':sum(x['sizeBytes'] for x in entries),'files':entries},indent=2)+'\n')
        (source/'verification/files.sha256').write_text(''.join(x['sha256']+'  '+x['path']+'\n' for x in entries))
        (source / 'dataset-manifest.json').unlink()
        write_manifest('20261016-120200Z');publish_source();receive()
        expect((working/'files/a.txt').read_text()=='alpha changed\n','changed file not updated')
        expect((working/'files/new.txt').exists(),'new file absent')
        expect(not (working/'files/nested/b.bin').exists(),'deleted file survived --delete')
        expect((snapshot/'backup/pluto/diaries-backup/files/a.txt').read_text()=='alpha\n', 'snapshot mutated')
        print('PASS: incremental changed/added/deleted files; older snapshot unchanged')
        # Missing source marker means next receive fails closed and revokes eligibility.
        run(ssh+['rm','-f',shlex.quote(remote+'/.diaries-backup-fixed-verified.json')])
        failure=receive(success=False)
        expect(failure.returncode!=0,'receive unexpectedly succeeded without source marker')
        expect(not marker.exists(), 'eligibility marker survived failed receive')
        expect((snapshot/'backup/pluto/diaries-backup/files/a.txt').read_text()=='alpha\n','snapshot damaged after failure')
        print('PASS: rejected/failed receive invalidates eligibility and retains previous snapshot')
        publish_source();receive()
        expect(json.loads(marker.read_text())['snapshotEligible'],'retry not verified')
        run([sys.executable,str(a.manifest_tool),'verify','--backup-dir',str(working),'--allow-fixed-working-root'])
        print('PASS: retry restores eligibility after independent schema-2 validation')
    finally:
        if remote and remote.startswith('/tmp/diaries-0036-btrfs-'):
            run(ssh+['rm','-rf','--',shlex.quote(remote)],check=False)
        # Delete only exact freshly created disposable Btrfs subvolumes; no recursive rm of the subvolumes.
        for vol in reversed(created):
            result=run(['btrfs','subvolume','delete',str(vol)],check=False)
            if result.returncode:
                print('CLEANUP REQUIRED: '+str(vol)+' '+result.stderr.strip(),file=sys.stderr)
        shutil.rmtree(local_source,ignore_errors=True)
    print('PASS: disposable Btrfs receiver rehearsal completed (no production paths touched)')

if __name__=='__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print('FAIL:',str(exc),file=sys.stderr);sys.exit(1)
