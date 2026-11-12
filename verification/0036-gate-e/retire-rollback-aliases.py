#!/usr/bin/env python3
"""0036 Gate E Stage 2: guarded reversible symlink-only retirement on pluto/mars."""
import argparse
import json
import subprocess
import sys

HOSTS = {
    'pluto': dict(base='/home/richard/projects/diaries/data', service='diaries-complete-backup-publish.service', timer='diaries-complete-backup-publish.timer', held=['20261009-153243Z','20261009-154847Z','20261015-003023Z']),
    'mars': dict(base='/media/usb/@data/backup/pluto', service='diaries-pull.service', timer='diaries-pull.timer', held=['20261007-145013Z','20261009-154847Z','20261015-003023Z']),
}
APPROVAL='0036-GATE-E-RETIRE-TWO-ALIASES-ONLY'
SHA='58e594a6327e20a0fe4800e2b24871458dfc7742cb217f2a7be136ba162ea6e4'
REMOTE=r'''
import hashlib,json,os,pathlib,subprocess,sys
cfg=json.loads(%CFG%)
mode=cfg['mode']
base=pathlib.Path(cfg['base']); root=base/'.diaries-backup-generations'
old=base/'diaries-backup.pre-0036-rollback'; retired=base/'diaries-backup.pre-0036-rollback.retired'
relative='.diaries-backup-generations/20261016-003019Z'
target=root/'20261016-003019Z'; current=base/'diaries-backup'; hold=root/'.0036-retirement-hold'
def run(*args):
 p=subprocess.run(args,capture_output=True,text=True)
 return p.returncode,p.stdout.strip()
def guard():
 if base.is_symlink() or root.is_symlink() or not root.is_dir(): raise RuntimeError('unexpected generations root')
 if current.is_symlink() or not current.is_dir(): raise RuntimeError('fixed repository missing or symlink')
 if target.is_symlink() or not target.is_dir(): raise RuntimeError('rollback target missing or symlink')
 mf=target/'dataset-manifest.json'
 if mf.is_symlink() or not mf.is_file(): raise RuntimeError('rollback manifest missing or symlink')
 b=mf.read_bytes(); d=json.loads(b)
 if hashlib.sha256(b).hexdigest()!=cfg['sha']: raise RuntimeError('rollback manifest checksum mismatch')
 if (d.get('schemaVersion'),d.get('logicalDataset'),d.get('backupId'))!=(2,'production','20261016-003019Z'): raise RuntimeError('rollback manifest identity mismatch')
 if hold.is_symlink() or not hold.is_dir(): raise RuntimeError('retirement hold missing')
 names=sorted(x.name for x in hold.iterdir() if x.is_dir() and not x.is_symlink())
 if names!=sorted(cfg['held']): raise RuntimeError('held generation inventory changed: '+repr(names))
 rc,s=run('systemctl','is-active',cfg['service'])
 if s!='inactive': raise RuntimeError('service not inactive: '+s)
 rc,t=run('systemctl','is-active',cfg['timer']); rc2,e=run('systemctl','is-enabled',cfg['timer'])
 if rc or rc2 or t!='active' or e!='enabled': raise RuntimeError('timer not active/enabled')
 if old.is_symlink() and not retired.exists() and not retired.is_symlink() and os.readlink(old)==relative: state='active'
 elif retired.is_symlink() and not old.exists() and not old.is_symlink() and os.readlink(retired)==relative: state='retired'
 else: raise RuntimeError('alias state ambiguous/unsafe: old='+str(old.is_symlink())+' retired='+str(retired.is_symlink()))
 return state
try:
 before=guard()
 if mode=='retire':
  if before!='active': raise RuntimeError('expected active alias before retirement')
  os.rename(old,retired)
 elif mode=='restore':
  if before!='retired': raise RuntimeError('expected retired alias before restore')
  os.rename(retired,old)
 after=guard()
 if mode=='retire' and after!='retired': raise RuntimeError('post-retirement verification failed')
 if mode=='restore' and after!='active': raise RuntimeError('post-restore verification failed')
 print(json.dumps({'host':cfg['host'],'mode':mode,'before':before,'after':after,'target_sha256':cfg['sha'],'current_fixed_repository':'PRESERVED','target_generation':'PRESERVED','held_generations':len(cfg['held']),'timer':'ACTIVE_ENABLED','operation':'SYMLINK_RENAME' if mode in ('retire','restore') else 'NONE'},indent=2))
except Exception as exc:
 print('BLOCKED: '+str(exc),file=sys.stderr);sys.exit(4)
'''
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=('plan','retire','restore'),default='plan')
    p.add_argument('--confirm',default='')
    p.add_argument('--host',choices=('pluto','mars'),help='For recovery from partial two-host execution; plan always checks the selected host only')
    args=p.parse_args()
    if args.mode=='retire' and args.confirm!=APPROVAL:
        p.error('retirement requires --confirm '+APPROVAL)
    if args.mode=='restore' and args.confirm!='0036-GATE-E-RESTORE-ALIAS':
        p.error('restore requires --confirm 0036-GATE-E-RESTORE-ALIAS')
    for host in ([args.host] if args.host else ['pluto','mars']):
        cfg=dict(HOSTS[host],host=host,mode=args.mode,sha=SHA)
        code=REMOTE.replace('%CFG%',repr(json.dumps(cfg)))
        r=subprocess.run(['ssh','-o','BatchMode=yes',host,'python3 -'],input=code,text=True,capture_output=True)
        print('=== '+host+' ===',flush=True)
        if r.stdout: print(r.stdout,end='')
        if r.stderr: print(r.stderr,file=sys.stderr,end='')
        if r.returncode:
            print('STOP: '+host+' returned '+str(r.returncode)+'; inspect both hosts before retry',file=sys.stderr)
            return r.returncode
    return 0
if __name__=='__main__':sys.exit(main())
