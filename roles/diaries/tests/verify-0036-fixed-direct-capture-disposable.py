#!/usr/bin/env python3
"""Disposable exercise of 0036 direct fixed capture control flow and real rsync.

PostgreSQL, manifest writer and schema validator are simulated; do not mistake
this for production integration or a full schema-2 verification.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'files/sync/scripts'
spec=importlib.util.spec_from_file_location('fixed_capture_under_test',ROOT/'fixed-dataset-capture.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

class P:
    live_rel='diaries-test'
    context={'database_data':'db','files_dir':'diaries-test','files_root':'/data/files'}
    def __init__(self,root):
        self.project=root
        self.compose=root/'compose.yaml'; self.env_file=root/'.env'
        self.published_root=root/'published'/'diaries-backup'
        self.manifest_tool=root/'manifest-tool'; self.verify_tool=root/'verify-tool'
        self.env={'DIARIES_0036_HOST_FILES_ROOT':str(root/'nas'), 'DIARIES_0036_HOST_MOUNT_ROOT':str(root/'nas'), 'DIARIES_0036_HOST_FILES_IDENTITY':self.live_rel}
        self.running=True
    def assert_db_ready(self): return ('diaries','tester')
    def responder_running(self): return self.running
    def stop_responder(self): self.running=False
    def start_responder(self): self.running=True
    def assert_responder_stopped(self): assert not self.running
    def pg_restore_list(self,p): assert p.read_bytes().startswith(b'CUSTOM')
    def image_count(self): return 0
    def dc_output(self,*a): return 'image:test'

class Prod:
    DB_SERVICE='postgres'; RESPONDER_SERVICE='responder'; DATASET='diaries'
    n=0
    @staticmethod
    def fail(msg): raise RuntimeError(msg)
    @staticmethod
    def iso_now(): return '2026-10-15T19:00:00+00:00'
    @staticmethod
    def new_backup_id():
        Prod.n+=1
        return f'20261015-19{Prod.n:02d}00Z'
    @staticmethod
    def write_json(path,obj): path.write_text(json.dumps(obj))
    @staticmethod
    def validate_sql_dump(path): assert path.read_bytes().startswith(b'-- SQL')

real_run=subprocess.run

def scenario(root):
    p=P(root); nas=root/'nas'; nas.mkdir(); (nas/'same.txt').write_text('unchanged'); (nas/'changing.txt').write_text('old'); (nas/'obsolete.txt').write_text('remove'); (nas/'.image-staging').mkdir()
    p.published_root.parent.mkdir()
    writes=[]; failure=[None]
    def subprocess_mock(args,**kw):
        if args[0]=='docker':
            assert '--env-file' in args and str(p.env_file) in args
            if failure[0]=='dump' and '--format=plain' in args: return subprocess.CompletedProcess(args,1)
            fmt=next(x for x in args if x.startswith('--format='))
            kw['stdout'].write(b'CUSTOM dump' if fmt=='--format=custom' else b'-- SQL dump')
            return subprocess.CompletedProcess(args,0)
        return real_run(args,**kw)
    def run_mock(args):
        if args[0]=='rsync':
            cp=real_run(args,capture_output=True,text=True)
            if cp.returncode: raise RuntimeError(cp.stderr)
        elif args[1]==str(p.verify_tool):
            assert (p.published_root/'files/same.txt').exists()
        elif args[1]==str(p.manifest_tool):
            if 'write' in args:
                bid=args[args.index('--fixed-backup-id')+1]
                (p.published_root/'dataset-manifest.json').write_text(json.dumps({'schemaVersion':2,'backupId':bid}))
                writes.append(bid)
            elif 'verify' in args:
                assert (p.published_root/'dataset-manifest.json').exists()
        else: raise AssertionError(args)
    with patch.object(sys.modules['__main__'],'fail',Prod.fail,create=True), patch.object(sys.modules['__main__'],'run',run_mock,create=True), patch.object(sys.modules['__main__'],'DB_SERVICE',Prod.DB_SERVICE,create=True), patch.object(sys.modules['__main__'],'RESPONDER_SERVICE',Prod.RESPONDER_SERVICE,create=True), patch.object(sys.modules['__main__'],'DATASET',Prod.DATASET,create=True), patch.object(sys.modules['__main__'],'iso_now',Prod.iso_now,create=True), patch.object(sys.modules['__main__'],'new_backup_id',Prod.new_backup_id,create=True), patch.object(sys.modules['__main__'],'write_json',Prod.write_json,create=True), patch.object(sys.modules['__main__'],'validate_sql_dump',Prod.validate_sql_dump,create=True), patch.object(mod.os.path,'ismount',lambda x: Path(x)==nas), patch.object(mod.subprocess,'run',subprocess_mock):
        mod.execute(p,preflight=True)
        assert not p.published_root.exists()
        mod.execute(p,preflight=False)
        marker=p.published_root.parent/'.diaries-backup-fixed-verified.json'
        assert marker.exists() and p.running
        inode=(p.published_root/'files/same.txt').stat().st_ino
        (nas/'changing.txt').write_text('new'); (nas/'added.txt').write_text('added'); (nas/'obsolete.txt').unlink()
        mod.execute(p,preflight=False)
        assert marker.exists() and (p.published_root/'files/added.txt').exists()
        assert not (p.published_root/'files/obsolete.txt').exists()
        assert (p.published_root/'files/changing.txt').read_text()=='new'
        assert (p.published_root/'files/same.txt').stat().st_ino==inode
        failure[0]='dump'
        try: mod.execute(p,preflight=False)
        except RuntimeError as e: assert 'pg_dump failed' in str(e)
        else: raise AssertionError('simulated database failure was not detected')
        assert not marker.exists() and not p.running
        failure[0]=None
        mod.execute(p,preflight=False)
        assert marker.exists() and not p.running and len(writes)==3
    print('PASS: disposable preflight, initial fixed capture, rsync update/delete, stable inode, dump failure, invalidated marker, retry')
    print('NOTE: PostgreSQL and schema-2 writer/validator were simulated; production-host integration remains outstanding')

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='0036-direct-capture-') as folder: scenario(Path(folder))
