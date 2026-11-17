#!/usr/bin/env python3
"""Read-only host-local Diaries dataset history and manifest-identity summary."""
import argparse
import json
import subprocess
import sys
import unicodedata

HISTORY = '/usr/local/sbin/diaries-backup-history'


def inspect_history(binary, config):
    try:
        result = subprocess.run([binary, '--config', config, '--json', 'list'],
                                text=True, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Diaries history check unavailable: ' + str(exc)) from exc
    try:
        data = json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError('Diaries history returned invalid JSON') from exc
    if not isinstance(data, dict) or not isinstance(data.get('backups'), list) or not isinstance(data.get('warnings'), list):
        raise RuntimeError('Diaries history returned an unexpected schema')
    if result.returncode not in (0, 2):
        raise RuntimeError('Diaries history failed: ' + (result.stderr.strip() or f'exit {result.returncode}'))
    # History reports exit 2 for manifest conflicts/warnings. Other exit-2
    # failures must not be mistaken for a healthy empty history.
    if result.returncode == 2 and not (data['warnings'] or
            any(isinstance(item, dict) and item.get('status') == 'conflict'
                for item in data['backups'])):
        raise RuntimeError('Diaries history failed without a reported conflict or warning')
    return data


def report(args):
    try:
        data = inspect_history(args.history, args.config)
        rows = data['backups']
        # A retained manifest identity is not evidence of a fresh full-content verification.
        for row in rows:
            if not all(key in row for key in ('logicalDataset', 'backupId', 'snapshots', 'firstRetainedSnapshot', 'lastRetainedSnapshot', 'status')):
                raise RuntimeError('Diaries history row is missing required fields')
        rows = sorted(rows, key=lambda row: (row['lastRetainedSnapshot'], row['backupId']), reverse=True)
        conflicts = sum(row['status'] == 'conflict' for row in rows)
        warnings = data['warnings']
        status = 'degraded' if conflicts or warnings else 'healthy'
        return {
            'schema': 1, 'component': 'diaries', 'health': status,
            'evidence': 'retained manifest identity (not full file-content verification)',
            'distinctBackups': len(rows),
            'retainedOccurrences': sum(row['snapshots'] for row in rows),
            'conflictedBackups': conflicts,
            'latest': rows[0] if rows else None,
            'recent': rows[:args.limit], 'warnings': warnings,
        }
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        return {'schema': 1, 'component': 'diaries', 'health': 'error', 'error': str(exc)}



def visible_width(value):
    return sum(0 if unicodedata.combining(c) else
               2 if unicodedata.east_asian_width(c) in ('F', 'W') else 1
               for c in str(value))

def fit(value, width, right=False):
    value = str(value)
    pad = ' ' * max(0, width - visible_width(value))
    return (pad + value) if right else (value + pad)


def table(headers, rows):
    if not rows:
        return 'No retained backups found'
    widths = [max(visible_width(h), *(visible_width(row[i]) for row in rows)) for i, h in enumerate(headers)]
    def line(fields):
        return '  '.join((fit(v, widths[i], right=(i == 4)))
                         for i, v in enumerate(fields))
    return '\n'.join([line(headers), '  '.join('-' * n for n in widths)] + [line(row) for row in rows])


def display(r):
    print('DIARIES BACKUP STATUS')
    if r['health'] == 'error':
        print('UNAVAILABLE: ' + r['error'])
        return
    print('Evidence: ' + r['evidence'])
    print(f"Health: {r['health'].upper()}  Distinct backups: {r['distinctBackups']}  "
          f"Retained occurrences: {r['retainedOccurrences']}  Conflicts: {r['conflictedBackups']}")
    latest = r['latest']
    print('Latest retained backup: ' + (f"{latest['logicalDataset']}/{latest['backupId']} "
           f"(last occurrence {latest['lastRetainedSnapshot']} UTC)" if latest else 'none'))
    print('\nRECENT DIARIES BACKUPS')
    print(table(('Logical dataset', 'Backup ID', 'First retained UTC', 'Last retained UTC', 'Snapshots', 'Manifest identity'),
          [(x['logicalDataset'], x['backupId'], x['firstRetainedSnapshot'], x['lastRetainedSnapshot'], x['snapshots'],
            'conflict' if x['status'] == 'conflict' else 'valid') for x in r['recent']]))
    if r['warnings']:
        print('\nDIARIES HISTORY WARNINGS')
        print(table(('Snapshot', 'Reason'), [(str(x[0]), str(x[1])) for x in r['warnings']]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/btrfs-snapshot-manager.json')
    parser.add_argument('--history', default=HISTORY)
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.limit <= 100:
        parser.error('--limit must be between 0 and 100')
    result = report(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        display(result)
    return {'healthy': 0, 'degraded': 1, 'error': 2}[result['health']]


if __name__ == '__main__':
    sys.exit(main())
