#!/usr/bin/env python3
"""Read-only Stage 2 rollback alias and target assessment from mango. Never mutates."""
import hashlib
import json
import subprocess
import sys

HOSTS = {
 'pluto': {'base':'/home/richard/projects/diaries/data','service':'diaries-complete-backup-publish.service','timer':'diaries-complete-backup-publish.timer'},
 'mars': {'base':'/media/usb/@data/backup/pluto','service':'diaries-pull.service','timer':'diaries-pull.timer'},
}
TARGET = '20261016-003019Z'
SHA = '58e594a6' # informational prefix only; verify original live digest, do not fabricate full reference
REMOTE = r'''
import hashlib,json,os,pathlib,subprocess,sys
cfg=json.loads(%CONFIG%)
base=pathlib.Path(cfg['base']); root=base/'.diaries-backup-generations'
alias=base/'diaries-backup.pre-0036-rollback'; target=root/'20261016-003019Z'; current=base/'diaries-backup'; hold=root/'.0036-retirement-hold'
def status(*args):
 r=subprocess.run(['systemctl',*args],text=True,capture_output=True)
 return {'code':r.returncode,'value':r.stdout.strip()}
def data():
 if not alias.is_symlink(): raise RuntimeError('rollback alias is not symlink')
 if os.readlink(alias)!='.diaries-backup-generations/20261016-003019Z': raise RuntimeError('rollback alias target changed')
 if not target.is_dir() or target.is_symlink(): raise RuntimeError('protected generation missing or symlink')
 if not current.is_dir() or current.is_symlink(): raise RuntimeError('current fixed repository is not real directory')
 if root.is_symlink() or not root.is_dir(): raise RuntimeError('generations root unexpected')
 manifest=target/'dataset-manifest.json'
 if not manifest.is_file() or manifest.is_symlink(): raise RuntimeError('manifest missing or symlink')
 b=manifest.read_bytes(); d=json.loads(b)
 if d.get('schemaVersion')!=2 or d.get('logicalDataset')!='production' or d.get('backupId')!='20261016-003019Z': raise RuntimeError('unexpected manifest identity')
 if not hold.is_dir() or hold.is_symlink(): raise RuntimeError('Stage 1 retirement hold absent or invalid')
 held=sorted(x.name for x in hold.iterdir() if x.is_dir())
 if len(held)!=3: raise RuntimeError('Expected three held Stage 1 directories, got '+str(held))
 service=status('is-active',cfg['service']); timer=status('is-active',cfg['timer']); enabled=status('is-enabled',cfg['timer'])
 if service['value']!='inactive': raise RuntimeError('backup/pull service is not inactive')
 if timer['value']!='active' or enabled['value']!='enabled': raise RuntimeError('timer not enabled and active')
 return {'host':cfg['host'],'status':'READY_FOR_DECISION_NOT_APPROVED','current_fixed_repository':str(current),'alias':str(alias),'alias_raw_target':os.readlink(alias),'protected_target':str(target),'manifest_sha256':hashlib.sha256(b).hexdigest(),'held_stage1_count':len(held),'held_stage1_ids':held,'service':service,'timer':timer,'timer_enabled':enabled,'protected_target_is_subvolume':'NOT_CHECKED','operations_performed':'NONE'}
try: print(json.dumps(data(),indent=2))
except Exception as exc:
 print('BLOCKED: '+str(exc),file=sys.stderr); sys.exit(4)
'''
def main():
 for host,cfg in HOSTS.items():
  print('=== '+host+' ===',flush=True)
  code=REMOTE.replace('%CONFIG%',repr(json.dumps({**cfg,'host':host})))
  p=subprocess.run(['ssh','-o','BatchMode=yes',host,'python3 -'],input=code,text=True,capture_output=True)
  if p.stdout: print(p.stdout,end='')
  if p.stderr: print(p.stderr,file=sys.stderr,end='')
  if p.returncode:
   print('STOP: '+host+' returned '+str(p.returncode),file=sys.stderr);return p.returncode
 return 0
if __name__=='__main__':sys.exit(main())
