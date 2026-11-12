#!/usr/bin/env python3
"""0036 Gate E read-only remote checks; deliberately never deletes or modifies data."""
import argparse
import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

REMOTE = r'''
import hashlib, json, os, pathlib, re, sys
host=sys.argv[1]
base=pathlib.Path('/home/richard/projects/diaries/data') if host=='pluto' else pathlib.Path('/media/usb/@data/backup/pluto')
store=base/'.diaries-backup-generations'
alias=base/'diaries-backup.pre-0036-rollback'
current=base/'diaries-backup'
record={'host':host,'current_directory':current.is_dir() and not current.is_symlink(), 'alias_is_symlink':alias.is_symlink(),'alias_target':os.readlink(alias) if alias.is_symlink() else None,'generations':{},'references':[],'snapshot_candidates':[],'errors':[]}
if not store.is_dir(): record['errors'].append('generation store missing')
def metadata(p):
    if not p.is_file(): return {'state':'MISSING'}
    try:
        raw=p.read_bytes(); obj=json.loads(raw)
        return {'state':'PRESENT','sha256':hashlib.sha256(raw).hexdigest(),'backupId':obj.get('backupId'),'schemaVersion':obj.get('schemaVersion'),'logicalDataset':obj.get('logicalDataset')}
    except (OSError, ValueError) as exc: return {'state':'ERROR','reason':type(exc).__name__}
for item in sorted(store.iterdir()) if store.is_dir() else []:
    if not item.is_dir() or item.is_symlink(): continue
    m=metadata(item/'dataset-manifest.json')
    record['generations'][item.name]={'manifest':m,'alias_target':alias.is_symlink() and alias.resolve()==item.resolve(),'snapshot_matches':[]}
# Explicitly inspect fixed, finite repository locations; no files outside these roots.
scan=[pathlib.Path('/home/richard/projects/diaries/scripts'), pathlib.Path('/home/richard/scripts/backup'),pathlib.Path('/etc/systemd/system/diaries-complete-backup-publish.service'),pathlib.Path('/etc/systemd/system/diaries-pull.service')]
needles=('.diaries-backup-generations','pre-0036-rollback', '20261016-003019Z', '20261015-003023Z', '20261009-154847Z', '20261009-153243Z', '20261007-145013Z')
for root in scan:
    if not root.exists(): continue
    candidates=[root] if root.is_file() else (p for p in root.rglob('*') if p.is_file() and not p.is_symlink())
    for p in candidates:
        try:
            if p.stat().st_size > 2000000: continue
            lines=p.read_text(encoding='utf-8',errors='replace').splitlines()
            for no,line in enumerate(lines,1):
                if any(n in line for n in needles): record['references'].append({'file':str(p),'line':no,'matched':[n for n in needles if n in line]})
        except (OSError,PermissionError) as e: record['errors'].append('reference scan unreadable: '+str(p))
if host=='mars':
    snap_root=pathlib.Path('/media/usb/@snapshots/@data')
    if snap_root.is_dir():
        for snap in sorted(snap_root.iterdir()):
            if not snap.is_dir() or not re.fullmatch(r'\d{8}-\d{6}Z',snap.name): continue
            record['snapshot_candidates'].append(snap.name)
            for gen,desc in record['generations'].items():
                target=snap/'backup/pluto/.diaries-backup-generations'/gen/'dataset-manifest.json'
                sm=metadata(target)
                if sm['state']=='PRESENT' and sm.get('sha256')==desc['manifest'].get('sha256'):
                    desc['snapshot_matches'].append(snap.name)
                elif sm['state']=='ERROR': record['errors'].append('snapshot file unreadable: '+str(target))
else:
    record['snapshot_coverage']='NOT_APPLICABLE: pluto is ext4 and 0035 snapshots are on mars'
print(json.dumps(record,indent=2,sort_keys=True))
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output_dir',type=pathlib.Path)
    args=p.parse_args()
    if args.output_dir.exists():
        p.error('output directory exists; use a new directory to prevent overwriting evidence')
    args.output_dir.mkdir(parents=True)
    complete=True
    for host in ('pluto','mars'):
        # mars's 0035 snapshot repository is deliberately root-protected.
        # Use passwordless sudo only on mars for read-only metadata inspection.
        remote_command = f'sudo -n python3 - {host}' if host == 'mars' else f'python3 - {host}'
        proc=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=12',host,remote_command],input=REMOTE,capture_output=True,text=True,timeout=180)
        (args.output_dir/f'{host}.stdout.json').write_text(proc.stdout)
        (args.output_dir/f'{host}.stderr.txt').write_text(proc.stderr)
        if proc.returncode:
            complete=False
            print(f'{host}: ERROR rc={proc.returncode}; inspect stderr',file=sys.stderr)
        else:
            try:
                data=json.loads(proc.stdout)
                if data['errors']:
                    complete=False
                print(f"{host}: {len(data['generations'])} generations, {len(data['references'])} references, {len(data['errors'])} collector warnings")
            except (ValueError,KeyError):
                complete=False; print(f'{host}: invalid response',file=sys.stderr)
    (args.output_dir/'collection.json').write_text(json.dumps({'collected_utc':datetime.now(timezone.utc).isoformat(), 'complete':complete, 'readonly':True,'scope':'deployed script references and exact manifest matches inside retained mars snapshots; no payload validation'},indent=2)+'\n')
    return 0 if complete else 1
if __name__=='__main__': sys.exit(main())
