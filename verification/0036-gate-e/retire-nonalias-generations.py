#!/usr/bin/env python3
"""0036 Gate E stage 1: inspect or reversibly quarantine six known generations.
Run from mango; remote Python via SSH; no sudo, no deletion, no timer manipulation.
"""
import argparse
import json
import re
import subprocess
import sys

EXPECTED = {
    'pluto': {
        'base': '/home/richard/projects/diaries/data',
        'service': 'diaries-complete-backup-publish.service',
        'timer': 'diaries-complete-backup-publish.timer',
        'generations': {
            '20261009-153243Z': '0a1c738494843eb49c2ab321f9e4e984b0aeb9e20f9bc19799bc5fa78ba7e036',
            '20261009-154847Z': 'f2d74243ee10441acf6813059e4cb767d6a6399c603dc2e1357f082b52a43dc9',
            '20261015-003023Z': 'c64f94a5211a16506838e74686ecd95acd56f56f8e98caff6e14c4a4a9ce4b65',
        },
    },
    'mars': {
        'base': '/media/usb/@data/backup/pluto',
        'service': 'diaries-pull.service',
        'timer': 'diaries-pull.timer',
        'generations': {
            '20261007-145013Z': '88a8dacb986f2d054de31ba0101d1b7987b6c52d0c1ba721619b7ec822e56d11',
            '20261009-154847Z': 'f2d74243ee10441acf6813059e4cb767d6a6399c603dc2e1357f082b52a43dc9',
            '20261015-003023Z': 'c64f94a5211a16506838e74686ecd95acd56f56f8e98caff6e14c4a4a9ce4b65',
        },
    },
}
REMOTE = r'''
import hashlib, json, os, pathlib, subprocess, sys
cfg = json.loads(%CFG_JSON%); mode = %MODE%
base = pathlib.Path(cfg['base']); root = base / '.diaries-backup-generations'
hold = root / '.0036-retirement-hold'; alias = base / 'diaries-backup.pre-0036-rollback'
current = base / 'diaries-backup'; protected = root / '20261016-003019Z'

def fail(s):
    print('BLOCKED: ' + s, file=sys.stderr); sys.exit(4)
def systemctl(*args):
    r = subprocess.run(['systemctl', *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip()
if not root.is_dir() or root.is_symlink(): fail('generation root invalid')
if not current.is_dir() or current.is_symlink(): fail('current fixed repository invalid')
if not alias.is_symlink() or os.readlink(alias) != '.diaries-backup-generations/20261016-003019Z': fail('rollback alias unexpected')
if not protected.is_dir() or protected.is_symlink(): fail('rollback target missing or invalid')
if hold.is_symlink(): fail('retirement hold is symlink')
if hold.exists() and not hold.is_dir(): fail('retirement hold invalid')
if systemctl('is-active', cfg['service'])[1] != 'inactive':
    fail('one-shot service is not inactive (requires an inactive completed service)')
if systemctl('is-active', cfg['timer'])[1] != 'active' or systemctl('is-enabled', cfg['timer'])[1] != 'enabled':
    fail('required timer not active and enabled')
if current.stat().st_dev != root.stat().st_dev: fail('repository is on unexpected filesystem')
items=[]
for name, expected_hash in cfg['generations'].items():
    original = root/name; moved = hold/name
    if original.exists() and moved.exists(): fail(name + ' present in both locations')
    item = original if original.exists() else moved
    if not item.is_dir() or item.is_symlink(): fail(name + ' is missing, symlink or not directory')
    if item.stat().st_dev != root.stat().st_dev: fail(name + ' crosses filesystem')
    manifest = item/'dataset-manifest.json'
    if not manifest.is_file() or manifest.is_symlink(): fail(name + ' manifest invalid')
    contents = manifest.read_bytes()
    sha = hashlib.sha256(contents).hexdigest()
    if sha != expected_hash: fail(name + ' manifest digest changed: ' + sha)
    data = json.loads(contents)
    if data.get('backupId') != name or data.get('schemaVersion') != 2 or data.get('logicalDataset') != 'production':
        fail(name + ' manifest identity mismatches')
    items.append({'generation':name, 'location':'hold' if item == moved else 'active', 'sha256':sha})
# No current or alias-target generation may be moved.
if mode == 'quarantine':
    if all(i['location'] == 'hold' for i in items):
        print('ALREADY QUARANTINED; no changes')
    else:
        hold.mkdir(mode=0o700, exist_ok=True)
        if hold.stat().st_dev != root.stat().st_dev: fail('hold not on source filesystem')
        for i in items:
            if i['location'] == 'active':
                os.rename(root/i['generation'], hold/i['generation'])
                i['location'] = 'hold'
                print('QUARANTINED: ' + i['generation'])
if mode == 'restore':
    for i in items:
        if i['location'] == 'hold':
            os.rename(hold/i['generation'], root/i['generation'])
            i['location'] = 'active'
            print('RESTORED: ' + i['generation'])
if not protected.is_dir() or not alias.is_symlink() or not current.is_dir(): fail('postcheck protected path missing')
for i in items:
    if not (hold/i['generation'] if i['location']=='hold' else root/i['generation']).is_dir(): fail('postcheck generation missing')
print(json.dumps({'host':cfg['host'],'mode':mode,'generations':items,'rollback_target':'PRESERVED','fixed_repository':'PRESERVED','timer':'ACTIVE_ENABLED'},indent=2))
'''

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode', choices=['plan','quarantine','restore'], default='plan')
    p.add_argument('--confirm', default='', help='required exact token for quarantine or restore')
    args=p.parse_args()
    if args.mode != 'plan' and args.confirm != '0036-GATE-E-SIX-NONALIAS-ONLY':
        p.error('mutating modes require --confirm 0036-GATE-E-SIX-NONALIAS-ONLY')
    for host, data in EXPECTED.items():
        for generation, digest in data['generations'].items():
            if re.fullmatch(r'[0-9a-f]{64}', digest) is None:
                p.error(f'invalid expected SHA-256 for {host}/{generation}; no remote actions performed')
        cfg={**data,'host':host}
        print(f'=== {host}: {args.mode} ===', flush=True)
        # Use SSH stdin for remote Python; no shell-embedded code or script transfer.
        remote_code=REMOTE.replace('%CFG_JSON%',repr(json.dumps(cfg))).replace('%MODE%',repr(args.mode))
        r=subprocess.run(['ssh','-o','BatchMode=yes',host,'python3 -'],input=remote_code,text=True,capture_output=True)
        if r.stdout: print(r.stdout, end='')
        if r.stderr: print(r.stderr, file=sys.stderr, end='')
        if r.returncode: 
            print(f'STOP: {host} returned {r.returncode}; no later host processed',file=sys.stderr)
            return r.returncode
    return 0
if __name__ == '__main__': sys.exit(main())
