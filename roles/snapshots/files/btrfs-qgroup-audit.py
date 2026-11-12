#!/usr/bin/env python3
"""0039-DEF: read-only conservative level-0 qgroup/subvolume reconciliation.

No cleanup implementation or command execution facility is provided.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

QID = re.compile(r'^\d+/\d+$')
SIZE = re.compile(r'^\d+(?:\.\d+)?(?:[KMGTPE]i?B|B)$', re.I)
ROW = re.compile(r'^ID\s+(\d+)\s+gen\s+\d+\s+top level\s+\d+\s+path\s+(.+)$')
MAX_BYTES = 16 * 1024 * 1024

class AuditError(Exception):
    pass


def invoke(args):
    try:
        result = subprocess.run(args, capture_output=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuditError(f'command failed or timed out: {args[0:3]}: {type(exc).__name__}') from exc
    if result.returncode or result.stderr and b'ERROR:' in result.stderr.upper():
        raise AuditError(f'command unsuccessful: {args[0:3]}, exit={result.returncode}')
    if len(result.stdout) > MAX_BYTES:
        raise AuditError('command output exceeded audit limit')
    try:
        return result.stdout.decode('utf-8')
    except UnicodeError as exc:
        raise AuditError('non-UTF-8 output') from exc


def subvolumes(text):
    found = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        match = ROW.fullmatch(line.strip())
        if not match:
            raise AuditError(f'unrecognised subvolume row: {line[:120]}')
        sid, path = int(match.group(1)), match.group(2)
        if sid in found:
            raise AuditError(f'duplicate subvolume ID: {sid}')
        found[sid] = path
    return found


def qgroups(text):
    lines = text.splitlines()
    if len(lines) < 2:
        raise AuditError('missing qgroup header')
    header = lines[0].lower().split()
    if len(header) < 7 or header[:3] not in (['qgroupid', 'rfer', 'excl'], ['qgroupid', 'referenced', 'exclusive']):
        raise AuditError('unrecognised qgroup columns')
    if not (re.fullmatch(r'[-\s]+', lines[1]) and len(lines[1].split()) >= 7):
        raise AuditError('invalid header divider')
    # btrfs-progs 6.6 emits two-word headings ("Max referenced", "Max exclusive")
    # while 5.16 emits max_rfer/max_excl. These are headings only: data rows
    # still have single-token values in the same seven fixed positions.
    if header[3:] not in (
        ['max_rfer', 'max_excl', 'parent', 'child'],
        ['max_rfer', 'max_excl', 'parent', 'child', 'path'],
        ['max_referenced', 'max_exclusive', 'parent', 'child'],
        ['max_referenced', 'max_exclusive', 'parent', 'child', 'path'],
        ['max', 'referenced', 'max', 'exclusive', 'parent', 'child', 'path'],
    ):
        raise AuditError('unsupported limit/relationship column order')
    records = {}
    for line in lines[2:]:
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) < 7 or not QID.fullmatch(fields[0]):
            raise AuditError(f'invalid qgroup row: {line[:120]}')
        if fields[0] in records:
            raise AuditError(f'duplicate qgroup ID: {fields[0]}')
        if not all(SIZE.fullmatch(v) for v in fields[1:3]):
            raise AuditError(f'invalid usage: {fields[0]}')
        if not all(v == 'none' or SIZE.fullmatch(v) for v in fields[3:5]):
            raise AuditError(f'invalid qgroup limit: {fields[0]}')
        # Relationships may be comma-delimited IDs; anything else is ambiguous.
        for relation in fields[5:7]:
            if relation not in ('---', 'none', '-') and not all(QID.fullmatch(i) for i in relation.split(',')):
                raise AuditError(f'ambiguous qgroup relationship: {fields[0]}')
        records[fields[0]] = dict(rfer=fields[1], excl=fields[2], max_rfer=fields[3],
                                  max_excl=fields[4], parent=fields[5], child=fields[6],
                                  annotation=' '.join(fields[7:]))
    return records


def reconcile(before, after, group_text, deletion_text, *, full_manifest=False, inspect_ids=()):
    first = subvolumes(before)
    second = subvolumes(after)
    deleted = subvolumes(deletion_text)
    groups = qgroups(group_text)
    if first != second:
        raise AuditError('subvolume inventory changed during capture; no candidate report')
    if set(first) & set(deleted):
        raise AuditError('pending-deletion IDs also appear in active subvolumes')
    result = []
    for key, info in sorted(groups.items(), key=lambda x: tuple(map(int, x[0].split('/')))):
        level, sid = map(int, key.split('/'))
        if level != 0:
            category = 'higher-level'
        elif sid == 5 or sid in first:
            category = 'active'
        elif sid in deleted:
            category = 'pending-deletion'
        elif info['parent'] not in ('---', 'none', '-') or info['child'] not in ('---', 'none', '-'):
            category = 'related-protected'
        elif info['max_rfer'] != 'none' or info['max_excl'] != 'none':
            category = 'limited-protected'
        elif info['annotation'] and info['annotation'] not in ('<stale>',):
            category = 'ambiguous'
        else:
            category = 'unmatched-candidate'
        result.append(dict(id=key, category=category, **info))
    counts = {}
    for row in result:
        counts[row['category']] = counts.get(row['category'], 0) + 1
    digest = hashlib.sha256(json.dumps({'subvolumes': first, 'pending': deleted, 'qgroups': groups},
                                      sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    report = {'schema': 1, 'read_only': True, 'deletion_authorized': False,
              'fingerprint_sha256': digest, 'subvolume_count': len(first),
              'pending_deletion_count': len(deleted), 'qgroup_count': len(groups),
              'counts': counts, 'review_sample': [r for r in result if r['category'] not in ('active', 'higher-level')][:20]}
    indexed = {row['id']: row for row in result}
    if inspect_ids:
        report['inspected_qgroups'] = {qid: indexed.get(qid) for qid in inspect_ids}
    if full_manifest:
        # Complete evidence for offline review, not an approval or removal plan.
        report['manifest'] = {'qgroups': result,
                              'active_subvolumes': [{'id': sid, 'path': path}
                                                    for sid, path in sorted(first.items())],
                              'pending_subvolumes': [{'id': sid, 'path': path}
                                                     for sid, path in sorted(deleted.items())]}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--filesystem', required=True, help='Existing Btrfs mountpoint (read-only queries only)')
    parser.add_argument('--full-manifest', action='store_true',
                        help='Write complete JSON evidence to stdout; redirect locally, not to terminal')
    parser.add_argument('--inspect-id', action='append', default=[], metavar='0/ID',
                        help='Include a specific qgroup record in the bounded summary (repeatable)')
    args = parser.parse_args()
    path = Path(args.filesystem)
    try:
        if len(args.inspect_id) > 100 or any(not re.fullmatch(r'0/[1-9]\d*', value)
                                             for value in args.inspect_id):
            raise AuditError('invalid or excessive --inspect-id values')
        if not path.is_dir():
            raise AuditError('filesystem path is not an accessible directory')
        # Inventory twice to avoid reporting candidates across observed changes.
        first = invoke(['btrfs', 'subvolume', 'list', '-a', str(path)])
        pending = invoke(['btrfs', 'subvolume', 'list', '-d', str(path)])
        groups = invoke(['btrfs', 'qgroup', 'show', '-pcre', str(path)])
        second = invoke(['btrfs', 'subvolume', 'list', '-a', str(path)])
        report = reconcile(first, second, groups, pending,
                           full_manifest=args.full_manifest, inspect_ids=args.inspect_id)
        report['filesystem'] = str(path.resolve())
        print(json.dumps(report, indent=2, sort_keys=True))
    except AuditError as exc:
        print(f'AUDIT UNAVAILABLE: {exc}', file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
