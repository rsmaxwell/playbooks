#!/usr/bin/env python3
"""0049: host-aware read-only Btrfs collection/snapshot/replication health summary."""
import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import unicodedata

MANAGER = '/usr/local/sbin/btrfs-snapshot-manager'
REPLICATION = '/usr/local/bin/btrfs-replication'
SOURCE_PARENT = Path('/media/usb/@snapshots/.simple-agreed-parent.json')
RECEIVER_PARENT = Path('/@data/mars-received/.replication-state/.simple-agreed-parent.json')
STAMP = re.compile(r'^\d{8}-\d{6}Z$')


def execute(argv, timeout=45, *, env=None):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, env=env)
        return {'ok': proc.returncode == 0, 'exit': proc.returncode,
                'stdout': proc.stdout.strip(), 'error': proc.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'ok': False, 'error': str(exc), 'stdout': ''}


def parse_manager_status(output):
    result = {}
    for line in output.splitlines():
        if line.startswith('source='):
            result.setdefault('sources', []).append(line[len('source='):])
        elif line.startswith('retention='):
            result['retention'] = line[len('retention='):]
        elif line.startswith('complete_timestamp_sets='):
            for item in line.split(';'):
                k, v = item.split('=', 1)
                result[k] = int(v)
        elif '=' in line and ';' not in line:
            k, v = line.split('=', 1)
            result[k] = v
    return result


def load_accepted_marker(config):
    verification = config.get('verification', {})
    sources = {x['name']: x.get('path') for x in config.get('sources', [])}
    if not verification.get('required'):
        return {'state': 'not_configured'}
    parent = sources.get(verification.get('source_name'))
    relative = verification.get('marker_relative_path')
    if not parent or not isinstance(relative, str):
        return {'state': 'unavailable', 'reason': 'verification marker not configured'}
    rel = Path(relative)
    if rel.is_absolute() or not relative or any(part in ('.', '..') for part in rel.parts):
        return {'state': 'unavailable', 'reason': 'unsafe marker relative path'}
    root = Path(parent).resolve()
    path = root / rel
    try:
        if not path.resolve().is_relative_to(root):
            raise ValueError('marker escapes source directory')
        record = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(record, dict) or record.get('state') != 'verified-published' or record.get('snapshotEligible') is not True:
            return {'state': 'degraded', 'reason': 'marker is not verified and snapshot-eligible'}
        return {'state': 'healthy', 'backupId': record.get('backupId'),
                'logicalDataset': record.get('logicalDataset'), 'verifiedAt': record.get('verifiedAt')}
    except (OSError, ValueError) as exc:
        return {'state': 'unavailable', 'reason': str(exc)}


def local_parent(path):
    try:
        obj = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(obj, dict) or not isinstance(obj.get('parent'), dict):
            raise ValueError('missing parent in agreed-parent state')
        return {'state': 'available', 'parent': obj['parent'], 'prior': obj.get('prior'),
                'evidence': 'local agreed-parent record (not remote verification)'}
    except (OSError, ValueError) as exc:
        return {'state': 'unavailable', 'reason': str(exc)}


def service_status(unit):
    outcome = execute(['systemctl', 'show', unit, '-p', 'LoadState', '-p', 'ActiveState',
                       '-p', 'UnitFileState', '-p', 'Result', '-p', 'ExecMainStatus',
                       '-p', 'ExecMainExitTimestamp', '-p', 'NextElapseUSecRealtime'])
    if not outcome['ok']:
        return {'state': 'unavailable', 'reason': outcome.get('error') or 'systemd query failed'}
    fields = dict(line.split('=', 1) for line in outcome['stdout'].splitlines() if '=' in line)
    if fields.get('LoadState') == 'not-found':
        return {'state': 'unavailable', 'reason': f'{unit} not installed'}
    return {'state': 'available', 'properties': fields}


def report(args):
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        role = config.get('mode', 'source')
        if role not in ('source', 'receiver'):
            raise ValueError('unsupported endpoint mode')
    except (OSError, ValueError, TypeError) as exc:
        return {'schema': 1, 'health': 'error', 'error': f'cannot load configuration: {exc}'}
    issues = []
    status = execute([args.manager, '--config', args.config, 'status'])
    snapshots = {'state': 'available', **parse_manager_status(status['stdout'])} if status['ok'] else {
        'state': 'unavailable', 'reason': status.get('error') or status.get('stdout') or 'manager status failed'}
    if not status['ok']:
        issues.append('snapshot manager status unavailable')
    elif snapshots.get('qgroups_status') not in ('ok',):
        issues.append('qgroup state ' + str(snapshots.get('qgroups_status', 'unavailable')))
    inventory = execute([args.manager, '--config', args.config, 'list'])
    timestamps = []
    if inventory['ok']:
        timestamps = sorted({line.split()[0] for line in inventory['stdout'].splitlines()
                             if line.split() and STAMP.fullmatch(line.split()[0])})
        snapshots['firstSnapshot'] = timestamps[0] if timestamps else None
        snapshots['latestSnapshot'] = timestamps[-1] if timestamps else None
    else:
        issues.append('snapshot inventory unavailable')
        snapshots['inventoryError'] = inventory.get('error') or inventory.get('stdout')
    snapshots['retainedSnapshotSetsObserved'] = len(timestamps) if inventory['ok'] else None
    parent = local_parent(SOURCE_PARENT if role == 'source' else RECEIVER_PARENT)
    replication = {'localAgreedParent': parent, 'receiverVerification': 'not checked' if args.local_only else 'not available'}
    if parent['state'] != 'available':
        issues.append('local agreed-parent record unavailable')
    if role == 'source' and not args.local_only:
        # 0041 cutover: the scheduled push explicitly selects the dedicated
        # btrfs-send -> btrfs-receive transport. Read-only status must use the
        # same identity; the runtime's unset mode is a retained legacy path.
        # Do not change the replication protocol or the root-owned service wrapper.
        status_env = os.environ.copy()
        status_env['BTRFS_REPLICATION_IDENTITY_MODE'] = 'dedicated'
        result = execute([args.replication, 'sender', 'status'], env=status_env)
        try:
            data = json.loads(result['stdout']) if result['ok'] else None
        except ValueError:
            data = None
        if (not isinstance(data, dict) or data.get('receiver_parent_verified') is not True or
                data.get('relation') not in ('equal', 'receiver-ahead')):
            replication['remote'] = {'state': 'unavailable', 'reason': result.get('error') or 'unverified sender status'}
            issues.append('remote replication verification unavailable')
        else:
            replication['remote'] = {'state': 'verified', 'relation': data['relation'],
                                     'receiverParent': data.get('receiver', {}).get('parent'),
                                     'preflight': data.get('preflight')}
            replication['receiverVerification'] = 'verified'
    elif role == 'source':
        replication['remote'] = {'state': 'not_checked', 'reason': '--local-only'}
    else:
        # Receiver status only inspects the local endpoint; never performs SSH.
        result = execute([args.replication, 'receiver', 'status'])
        try:
            data = json.loads(result['stdout']) if result['ok'] else None
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get('state'), dict):
            replication['receiver'] = {'state': 'available', 'record': data['state']}
        else:
            replication['receiver'] = {'state': 'unavailable', 'reason': result.get('error') or 'receiver status failed'}
            issues.append('local receiver status unavailable')
    collection = load_accepted_marker(config) if role == 'source' else None
    if role == 'source' and collection['state'] in ('degraded', 'unavailable'):
        issues.append('verified collection marker unavailable')
    service_names = (('diaries-pull.service', 'diaries-pull.timer', 'btrfs-snapshot-create.timer',
                      'btrfs-snapshot-prune.timer', 'btrfs-push.service', 'btrfs-push.timer')
                     if role == 'source' else ('btrfs-receiver-prune.service', 'btrfs-receiver-prune.timer'))
    services = {name: service_status(name) for name in service_names}
    for name, unit in services.items():
        if unit['state'] != 'available':
            issues.append(f'{name}: {unit.get("reason", "unavailable")}')
        elif unit.get('properties', {}).get('Result') == 'failed':
            issues.append(f'{name}: last service result failed')
    # 'Exit timestamp' is not a proof of transferred data: keep service runs distinct.
    if role == 'source':
        pull = services.get('diaries-pull.service', {}).get('properties', {})
        collection['lastSuccessfulPullServiceRun'] = (pull.get('ExecMainExitTimestamp')
            if pull.get('Result') == 'success' and pull.get('ExecMainExitTimestamp') else None)
    push = services.get('btrfs-push.service', {}).get('properties', {}) if role == 'source' else {}
    last_completed_push = (push.get('ExecMainExitTimestamp')
                           if push.get('Result') == 'success' and push.get('ExecMainExitTimestamp') else None)

    return {'schema': 1, 'host': socket.gethostname().split('.')[0], 'role': role,
            'health': 'degraded' if issues else 'healthy', 'issues': issues,
            'collection': collection, 'snapshots': snapshots, 'replication': replication,
            'services': services, 'limits': {'remoteChecked': role == 'source' and not args.local_only,
                                            'lastSuccessfulPushCycle': last_completed_push,
                                            'lastVerifiedTransfer': 'unknown: no independent transfer receipt',
                                            'lastCompletedCycle': 'see systemd service Result/ExecMainExitTimestamp'},
            'verbose': args.verbose}



def visible_width(value):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1
               for c in str(value))

def fit(value, width, right=False):
    value = str(value)
    pad = ' ' * max(0, width - visible_width(value))
    return (pad + value) if right else (value + pad)


def table(headers, rows, numeric=()):
    if not rows:
        return 'No entries'
    widths = [max(visible_width(h), *(visible_width(row[i]) for row in rows)) for i, h in enumerate(headers)]
    def line(fields):
        return '  '.join((fit(v, widths[i], right=(i in numeric)))
                         for i, v in enumerate(fields))
    return '\n'.join([line(headers), '  '.join('-' * n for n in widths)] + [line(row) for row in rows])


def display(r):
    if r['health'] == 'error':
        print('BTRFS BACKUP STATUS: UNAVAILABLE')
        print(r['error'])
        return
    print(f"BTRFS BACKUP STATUS — {r['host']} ({r['role']})")
    print('Health: ' + r['health'].upper())
    if r['collection'] is not None:
        print('\nBACKUP COLLECTION')
        c = r['collection']
        print('Accepted published dataset: ' +
              (f"{c.get('logicalDataset')}/{c.get('backupId')} at {c.get('verifiedAt')}"
               if c['state'] == 'healthy' else f"{c['state']}: {c.get('reason', 'not configured')}"))
        print('Last successful collection service run: ' + str(c.get('lastSuccessfulPullServiceRun') or 'unknown'))
    s = r['snapshots']
    print('\nBTRFS SNAPSHOTS AND RETENTION')
    print('Repository: ' + str(s.get('snapshot_root', 'unavailable')))
    print('Retained sets (observed): ' + str(s.get('retainedSnapshotSetsObserved')))
    print('Oldest / newest (UTC): ' + str(s.get('firstSnapshot')) + ' / ' + str(s.get('latestSnapshot')))
    print('Retention: ' + str(s.get('retention', 'unavailable')))
    print('\nFILESYSTEM QGROUP HEALTH')
    print('Qgroups: ' + ', '.join(f'{key}={s.get(key, "unavailable")}' for key in
                                ('qgroups_status', 'qgroups_total', 'qgroups_stale', 'qgroups_under_deletion')))
    print('\nBTRFS REPLICATION')
    p = r['replication']['localAgreedParent']
    print('Local agreed parent: ' + (str(p['parent']) if p['state'] == 'available' else 'unavailable: ' + p['reason']))
    print('Locally recorded prior parent: ' + (str(p['prior']) if p['state'] == 'available' else 'unavailable'))
    remote = r['replication'].get('remote')
    if remote:
        print('Receiver: ' + remote['state'] + (': ' + str(remote.get('reason')) if 'reason' in remote else ''))
        if remote.get('preflight'):
            x = remote['preflight']
            print('\nNEXT PUSH PREFLIGHT')
            print(table(('Action', 'Candidate UTC', 'Parent UTC'),
                        [(x.get('action', '-'), x.get('source') or '-', x.get('parent') or '-')]))
    elif r['replication'].get('receiver'):
        print('Receiver state: ' + r['replication']['receiver']['state'])
    if r['role'] == 'source':
        print('Last successful push cycle: ' + str(r['limits']['lastSuccessfulPushCycle'] or 'unknown'))
    print('Last verified transfer: unknown (independent receipt not available)')
    print('\nSCHEDULED OPERATIONS')
    entries = []
    for unit, value in sorted(r['services'].items()):
        props = value.get('properties', {})
        entries.append((unit, props.get('ActiveState', value['state']), props.get('Result', '-'),
                        props.get('NextElapseUSecRealtime') or props.get('ExecMainExitTimestamp') or '-'))
    print(table(('Unit', 'Active', 'Result', 'Next/last execution (systemd)'), entries))
    if r['issues']:
        print('\nHEALTH WARNINGS')
        print(table(('Check', 'Detail'), [(str(i + 1), item) for i, item in enumerate(r['issues'])]))
    if r['verbose']:
        print('\nSNAPSHOT SOURCES')
        print(table(('Source',), [(x,) for x in s.get('sources', [])]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/btrfs-snapshot-manager.json')
    parser.add_argument('--manager', default=MANAGER)
    parser.add_argument('--replication', default=REPLICATION)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--local-only', action='store_true', help='never contact receiver over SSH')
    args = parser.parse_args(argv)
    result = report(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        display(result)
    return {'healthy': 0, 'degraded': 1, 'error': 2}[result['health']]


if __name__ == '__main__':
    sys.exit(main())
