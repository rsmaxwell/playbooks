#!/usr/bin/env python3
"""0036 experimental direct fixed working-dataset capture (opt-in only).

Requires a host-mounted NAS Files root.  It never operates on the legacy
symlink publisher path.  The fixed marker/lock protocol MUST be implemented
by mars before production activation; scheduling alone is insufficient.
"""
from __future__ import annotations
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def execute(p, *, preflight: bool):
    from importlib import import_module
    # Production module was loaded as __main__ in the parent process.
    prod = sys.modules['__main__']
    fail, run = prod.fail, prod.run
    dest = p.published_root
    source_setting = p.env.get('DIARIES_0036_HOST_FILES_ROOT', '')
    if not source_setting or not Path(source_setting).is_absolute():
        fail('DIARIES_0036_HOST_FILES_ROOT must be an explicit absolute host NAS Files path')
    source = Path(source_setting)
    if not source.is_dir() or source.is_symlink() or source.resolve() == Path('/'):
        fail('host NAS Files path unavailable, unsafe or not mounted')
    if dest.name != 'diaries-backup' or dest.is_symlink():
        fail('fixed working destination must be a non-symlink diaries-backup directory')
    if not dest.parent.is_dir() or source == dest or source in dest.parents or dest in source.parents:
        fail('unsafe NAS/destination path overlap')
    if not os.path.ismount(p.env.get('DIARIES_0036_HOST_MOUNT_ROOT', '')):
        fail('DIARIES_0036_HOST_MOUNT_ROOT must identify an existing mount point')
    mount = Path(p.env['DIARIES_0036_HOST_MOUNT_ROOT']).resolve(strict=True)
    if source.resolve() != mount and mount not in source.resolve().parents:
        fail('host Files path is not beneath the configured mounted filesystem')
    # Require source identity to be explicitly confirmed: prevents capturing
    # unrelated host directories if the CIFS mount drops or changes.
    if p.env.get('DIARIES_0036_HOST_FILES_IDENTITY') != p.live_rel:
        fail('host NAS selector identity does not match deployed Files selector')
    if not shutil_which('rsync'):
        fail('host rsync is required for 0036 fixed capture')
    p.assert_db_ready()
    if preflight:
        print('PREFLIGHT OK: host NAS mount, rsync, PostgreSQL and fixed path validated; no data modified')
        return
    if dest.exists() and not dest.is_dir():
        fail('invalid working dataset path')
    dest.mkdir(mode=0o700, exist_ok=True)
    lockpath = dest.parent / '.diaries-backup-fixed.lock'
    marker = dest.parent / '.diaries-backup-fixed-verified.json'
    if lockpath.is_symlink() or marker.is_symlink():
        fail('fixed backup lock/marker symlinks refused')
    with lockpath.open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker.unlink(missing_ok=True)
        # A failed capture leaves the working copy ineligible for mars snapshots.
        was_running = p.responder_running()
        started = prod.iso_now()
        stopped = False
        try:
            if was_running:
                p.stop_responder(); stopped = True
            else:
                p.assert_responder_stopped()
            # Inspect the same host Files root being copied; no helper container.
            staging = source / '.image-staging'
            if not staging.exists():
                disposition, count = 'empty', 0
            elif not staging.is_dir() or staging.is_symlink():
                fail('invalid NAS .image-staging directory')
            else:
                entries = list(staging.rglob('*'))
                count = len(entries)
                if not entries:
                    disposition = 'empty'
                elif len(entries) == 1 and entries[0].name == 'catalogue.lock' and entries[0].is_file() and entries[0].stat().st_size == 0:
                    disposition = 'excluded-benign'
                else:
                    fail('unexplained NAS .image-staging content; refusing backup')
            for item in source.rglob('*'):
                if '.image-staging' in item.relative_to(source).parts:
                    continue
                if item.is_symlink() or not (item.is_file() or item.is_dir()):
                    fail('NAS Files contains symlinks or special entries')
            (dest/'database').mkdir(exist_ok=True)
            (dest/'files').mkdir(exist_ok=True)
            db_name, db_user = p.assert_db_ready()
            # Fresh dumps are first generated in temporary files, then renamed.
            for fmt, target in [('custom','diaries.dump'), ('plain','diaries.sql')]:
                temporary = dest/'database'/('.'+target+'.incoming')
                try:
                    with temporary.open('wb') as output:
                        args=['docker','compose','--file',str(p.compose),'--env-file',str(p.env_file),
                              'exec','-T',prod.DB_SERVICE,'pg_dump',f'--format={fmt}',
                              '--no-owner','--no-privileges','--username',db_user,'--dbname',db_name]
                        result=subprocess.run(args,cwd=p.project,stdout=output)
                        if result.returncode: fail('pg_dump failed: '+fmt)
                    if fmt=='custom': p.pg_restore_list(temporary)
                    else: prod.validate_sql_dump(temporary)
                    os.replace(temporary,dest/'database'/target)
                finally:
                    temporary.unlink(missing_ok=True)
            # Exclude volatile files. rsync --checksum prevents false skips.
            run(['rsync','-rlt','--checksum','--delete','--delete-delay',
                 '--exclude=/.image-staging/', '--exclude=/.*.rsync-tmp/',
                 str(source)+'/',str(dest/'files')+'/'])
            # Independent checksum/content comparison, no extra full data copy.
            result=subprocess.run(['rsync','-rlt','--checksum','--delete','--dry-run','--itemize-changes',
                     '--exclude=/.image-staging/',str(source)+'/',str(dest/'files')+'/'],
                     capture_output=True,text=True)
            if result.returncode or result.stdout.strip():
                fail('NAS Files checksum comparison differs after transfer: '+result.stdout[:500])
            run([sys.executable,str(p.verify_tool),'--backup-dir',str(dest),
                 '--source-files-root',str(source)])
            image_count=p.image_count()
            runtime_images=[x for x in p.dc_output('config','--images').splitlines() if x.strip()]
            application_identity=base64.b64encode(json.dumps({'runtimeImages':runtime_images},separators=(',',':')).encode()).decode()
            backup_id=prod.new_backup_id()
            run(_manifest_args(p,prod,dest,db_name,application_identity,image_count,disposition,count,started,backup_id,was_running,stopped))
            run([sys.executable,str(p.manifest_tool),'verify','--backup-dir',str(dest),'--allow-fixed-working-root'])
            data=(dest/'dataset-manifest.json').read_bytes()
            manifest=json.loads(data)
            payload={'schemaVersion':1,'backupId':manifest['backupId'],
                     'manifestSha256':hashlib.sha256(data).hexdigest(),'root':str(dest)}
            temp=marker.with_name(marker.name+'.tmp')
            try:
                temp.write_text(json.dumps(payload,sort_keys=True)+'\n')
                os.replace(temp,marker)
            finally:
                temp.unlink(missing_ok=True)
            if was_running: p.start_responder()
            print('PASS: fixed schema-2 dataset verified:',manifest['backupId'])
        except Exception:
            # Existing 0033 safety contract: leave responder stopped on failure.
            try: p.stop_responder()
            except Exception: pass
            raise


def _manifest_args(p,prod,dest,db_name,identity,count,disposition,staging_count,started,backup_id,was_running,stopped):
    # The manifest writer derives backup ID from its capture-state file.
    prod.write_json(dest/'capture-state.json',{
        'schemaVersion':1,'feature':'0033-FEAT','launchMode':'production',
        'backupId':backup_id,'startedAt':started,
        'writer':{'service':prod.RESPONDER_SERVICE,'wasRunning':was_running,'stoppedByBackup':stopped},
        'staging':{'disposition':disposition,'entryCount':staging_count}})
    return [sys.executable,str(p.manifest_tool),'write','--backup-dir',str(dest),
            '--fixed-backup-id',backup_id,'--force',
            '--logical-dataset',prod.DATASET,'--launch-mode','production','--known-consumer','production',
            '--database-storage-identity',p.context['database_data'],'--database-name',db_name,
            '--files-selector',p.context['files_dir'],'--files-root',p.context['files_root'],
            '--application-identity-base64',identity,
            '--writer-method','docker-compose-service-stop','--writer',f'docker:production/{prod.RESPONDER_SERVICE}',
            '--writer-evidence',f'{prod.RESPONDER_SERVICE} stopped/rechecked before capture',
            '--image-row-count',str(count),'--catalogued-file-count',str(count),
            '--staging-disposition',disposition,'--staging-entry-count',str(staging_count),
            '--staging-note','transient .image-staging excluded',
            '--started-at',started,'--completed-at',prod.iso_now()]


def shutil_which(name):
    import shutil
    return shutil.which(name)
