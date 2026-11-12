#!/usr/bin/env python3
"""Read-only operational summary of Diaries backup history, snapshots, pull and off-site replication."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

MANAGER = '/usr/local/sbin/btrfs-snapshot-manager'
HISTORY = '/usr/local/sbin/diaries-backup-history'
PUSH = '/usr/local/bin/btrfs-simplified-replication'


def command(args, timeout=40):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return {'ok': r.returncode == 0, 'exit': r.returncode, 'stdout': r.stdout.strip(),
                'error': r.stderr.strip() if r.returncode else ''}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'ok': False, 'error': str(exc), 'stdout': ''}


def json_command(args):
    outcome = command(args)
    if outcome['stdout']:
        try:
            outcome['data'] = json.loads(outcome['stdout'])
        except ValueError:
            outcome['ok'] = False
            outcome['error'] = 'invalid JSON response: ' + outcome['stdout'][:160]
    return outcome


def read_marker(config):
    verification = config.get('verification') or {}
    sources = {s['name']: s['path'] for s in config.get('sources', [])}
    name = verification.get('source_name')
    relative = verification.get('marker_relative_path')
    if not verification.get('required') or not relative or name not in sources:
        return {'ok': False, 'error': 'verified Diaries marker not configured'}
    # Ensure the inventory-defined relative path cannot escape the source directory.
    path = Path(relative)
    if path.is_absolute() or any(part in ('..', '.') for part in path.parts):
        return {'ok': False, 'error': 'unsafe marker relative path'}
    root = Path(sources[name]).resolve()
    path = root / path
    try:
        if not path.resolve().is_relative_to(root):
            raise ValueError('marker outside source')
        record = json.loads(path.read_text(encoding='utf-8'))
        return {'ok': record.get('snapshotEligible') is True and record.get('state') == 'verified-published',
                'path': str(path), 'data': record}
    except (OSError, ValueError) as exc:
        return {'ok': False, 'path': str(path), 'error': str(exc)}


def report(args):
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'error': 'Cannot read snapshot configuration: ' + str(exc)}
    snapshot = command([args.manager, '--config', args.config, 'status'])
    history = json_command([args.history, '--config', args.config, '--json', 'list'])
    marker = read_marker(config)
    # The simplified sender offers one guarded read-only inspection of the
    # local agreed-parent state, actual source and receiver Btrfs identities,
    # and next eligible snapshot. Never invoke `sender cycle` here.
    # Root is required to access the 0600 agreed-parent record; when run as an
    # ordinary operator sudo must be explicitly authorised by the host.
    privileged = ['sudo', '-n'] if os.geteuid() != 0 else []
    inspection = json_command(privileged + [args.push, 'sender', 'status'])
    payload = inspection.get('data') if inspection['ok'] else None
    if (not isinstance(payload, dict) or
            payload.get('receiver_parent_verified') is not True or
            payload.get('relation') not in ('equal', 'receiver-ahead') or
            not isinstance(payload.get('preflight'), dict) or
            not isinstance(payload.get('receiver'), dict)):
        inspection['ok'] = False
        inspection['error'] = inspection.get('error') or 'invalid simplified sender status'
        replication = {'ok': False, 'error': inspection['error']}
        receiver = {'ok': False, 'error': inspection['error']}
    else:
        replication = {'ok': True, 'data': payload['preflight']}
        parent = payload['receiver'].get('parent')
        if isinstance(parent, dict) and {'timestamp', 'uuid'} <= set(parent):
            receiver = {'ok': True, 'latest': {
                'snapshot': parent['timestamp'], 'source_uuid': parent['uuid']},
                'relation': payload['relation'], 'identity_verified': True}
        else:
            receiver = {'ok': False, 'error': 'missing remote agreed parent'}
            replication = {'ok': False, 'error': 'missing remote agreed parent'}
    if isinstance(history.get('data'), dict):
        rows = history['data'].get('backups', [])
        history['count'] = len(rows)
        history['latest'] = max(rows, key=lambda v: v['backupId'], default=None)
        history['recent'] = sorted(rows, key=lambda v: v['backupId'], reverse=True)[:args.limit]
        history.pop('data', None)
    return {'snapshot': snapshot, 'history': history, 'lastVerifiedPull': marker,
            'replicationPreflight': replication, 'offsite': receiver}


def display(record):
    if 'error' in record:
        print('ERROR: ' + record['error'])
        return
    print('DIARIES BACKUP STATUS (read-only)')
    snapshot = record['snapshot']
    print('\nSNAPSHOT HEALTH')
    print(snapshot['stdout'] if snapshot['ok'] else 'UNAVAILABLE: ' + snapshot.get('error', 'unknown'))
    print('\nBACKUP HISTORY')
    h = record['history']
    if h['ok']:
        print(f"Retained distinct backups: {h['count']}")
        for item in h['recent']:
            print(f"  {item['backupId']} dataset={item['logicalDataset']} occurrences={item['snapshots']} status={item['status']}")
    else:
        print('UNAVAILABLE: ' + (h.get('error') or h.get('stdout') or 'unknown'))
    print('\nLAST VERIFIED PULL (CURRENT RECEIVING MARKER)')
    m = record['lastVerifiedPull']
    if m['ok']:
        v = m['data']
        print(f"  backupId={v.get('backupId')} logicalDataset={v.get('logicalDataset')} verifiedAt={v.get('verifiedAt')}")
        print(f"  sourceIdentity={v.get('sourceIdentity')} snapshotEligible={v.get('snapshotEligible')}")
    else:
        print('UNAVAILABLE: ' + m.get('error', 'not verified'))
    print('\nLAST ACCEPTED OFF-SITE REPLICATION')
    o = record['offsite']
    if o['ok']:
        v = o['latest']
        print(f"  snapshot={v['snapshot']} source_uuid={v.get('source_uuid')} (receiver identity verified)" if v else '  No agreed parent reported')
    else:
        print('UNAVAILABLE: ' + (o.get('error') or 'unknown'))
    p = record['replicationPreflight']
    print('\nNEXT SIMPLIFIED PUSH PREFLIGHT (READ-ONLY)')
    if p['ok'] and isinstance(p.get('data'), dict):
        v = p['data']
        print(f"  action={v.get('action')} source={v.get('source')} parent={v.get('parent')}")
    else:
        print('UNAVAILABLE: ' + (p.get('error') or 'unknown'))
    print('\nNote: history verification configuration limitation is tracked under 0035-FEAT.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/btrfs-snapshot-manager.json')
    parser.add_argument('--manager', default=MANAGER)
    parser.add_argument('--history', default=HISTORY)
    parser.add_argument('--push', default=PUSH)
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if args.limit < 0 or args.limit > 100:
        parser.error('--limit must be between 0 and 100')
    result = report(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        display(result)
    return 2 if 'error' in result else 0

if __name__ == '__main__':
    sys.exit(main())
