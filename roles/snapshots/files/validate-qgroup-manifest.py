#!/usr/bin/env python3
"""0039-DEF offline, fail-closed validation of a saved qgroup audit manifest.

Reads only local evidence; never invokes Btrfs, SSH or filesystem mutations.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

UUID = re.compile(r'\buuid:\s*([0-9a-fA-F-]{36})\b')
QID = re.compile(r'^(\d+)/(\d+)$')
ABSENT = ('-', '---', 'none')
FIELDS = ('rfer', 'excl', 'max_rfer', 'max_excl', 'parent', 'child', 'annotation')


class ValidationError(Exception):
    pass


def require(test, message):
    if not test:
        raise ValidationError(message)


def validate(data, identity, expected_host=None, expected_uuid=None):
    require(isinstance(data, dict), 'manifest root is not an object')
    require(data.get('schema') == 1 and data.get('read_only') is True and
            data.get('deletion_authorized') is False, 'unsafe/unknown manifest schema or flags')
    filesystem = data.get('filesystem')
    require(filesystem in ('/', '/media/usb'), 'unexpected filesystem target')
    require(isinstance(data.get('fingerprint_sha256'), str) and
            re.fullmatch('[0-9a-f]{64}', data['fingerprint_sha256']), 'invalid inventory fingerprint')
    sections = data.get('manifest')
    require(isinstance(sections, dict) and set(sections) ==
            {'qgroups', 'active_subvolumes', 'pending_subvolumes'}, 'incomplete manifest sections')
    for name in sections:
        require(isinstance(sections[name], list), f'{name} is not a list')

    def subvolumes(name):
        result = {}
        for row in sections[name]:
            require(isinstance(row, dict) and set(row) == {'id', 'path'}, f'invalid {name} record')
            sid, path = row['id'], row['path']
            require(type(sid) is int and sid > 0 and isinstance(path, str) and path,
                    f'invalid {name} identifier/path')
            require(sid not in result, f'duplicate {name} identifier {sid}')
            result[sid] = path
        return result

    active = subvolumes('active_subvolumes')
    pending = subvolumes('pending_subvolumes')
    require(not set(active).intersection(pending), 'active/pending overlap')
    raw_groups = {}
    counts = Counter()
    records = {}
    for row in sections['qgroups']:
        require(isinstance(row, dict) and set(row) == {'id', 'category', *FIELDS}, 'invalid qgroup record')
        qid = row['id']
        require(isinstance(qid, str) and QID.fullmatch(qid), 'invalid qgroup ID')
        level, sid = map(int, qid.split('/'))
        require(qid == f'{level}/{sid}' and qid not in raw_groups, f'duplicate/noncanonical qgroup {qid}')
        require(all(isinstance(row[f], str) for f in FIELDS), f'non-string qgroup field {qid}')
        for relation in ('parent', 'child'):
            value = row[relation]
            require(value in ABSENT or all(QID.fullmatch(v) for v in value.split(',')),
                    f'ambiguous relationship {qid}')
        info = {field: row[field] for field in FIELDS}
        raw_groups[qid] = info
        if level != 0:
            category = 'higher-level'
        elif sid == 5 or sid in active:
            category = 'active'
        elif sid in pending:
            category = 'pending-deletion'
        elif info['parent'] not in ABSENT or info['child'] not in ABSENT:
            category = 'related-protected'
        elif info['max_rfer'] != 'none' or info['max_excl'] != 'none':
            category = 'limited-protected'
        elif info['annotation'] and info['annotation'] != '<stale>':
            category = 'ambiguous'
        else:
            category = 'unmatched-candidate'
        require(row['category'] == category, f'wrong category for {qid}')
        counts[category] += 1
        records[qid] = row

    require(data.get('qgroup_count') == len(raw_groups) and
            data.get('subvolume_count') == len(active) and
            data.get('pending_deletion_count') == len(pending), 'summary inventory counts differ')
    require(data.get('counts') == dict(counts), 'summary classifications differ')
    payload = {'subvolumes': active, 'pending': pending, 'qgroups': raw_groups}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    require(digest == data['fingerprint_sha256'], 'inventory fingerprint mismatch')
    sample = [row for row in sorted(records.values(), key=lambda r: tuple(map(int, r['id'].split('/'))))
              if row['category'] not in ('active', 'higher-level')][:20]
    require(data.get('review_sample') == sample, 'review sample differs from full manifest')
    for qid, row in data.get('inspected_qgroups', {}).items():
        require(row == records.get(qid), f'inspected record mismatch {qid}')

    require(isinstance(identity, str), 'missing identity evidence')
    found = UUID.search(identity)
    require(found is not None, 'identity evidence lacks filesystem UUID')
    uuid = found.group(1).lower()
    require(re.search(r'=== Mount identity ===\s*\n', identity) is not None and
            re.search(r'=== Quota rescan status ===\s*\nno rescan operation in progress', identity) is not None,
            'missing mount evidence or rescan not confirmed idle')
    require(re.search(r'^' + re.escape(filesystem) + r'\s+\S+\s+btrfs\s+', identity, re.M) is not None,
            'identity mount does not match manifest filesystem')
    require(re.search(r'\bsubvolid=5\b', identity) is not None, 'identity is not top-level mount')
    if expected_host:
        require(re.search(r'=== Host and capture time ===\s*\n' + re.escape(expected_host) + r'\s*\n', identity) is not None,
                'identity host mismatch')
    if expected_uuid:
        require(uuid == expected_uuid.lower(), 'identity UUID does not match expected UUID')
    return {'result': 'PASS', 'filesystem': filesystem, 'uuid': uuid,
            'qgroups': len(raw_groups), 'active_subvolumes': len(active),
            'pending_subvolumes': len(pending), 'counts': dict(counts),
            'fingerprint_sha256': digest, 'deletion_authorized': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True)
    p.add_argument('--identity', required=True)
    p.add_argument('--expected-host', choices=['mars', 'backup'], required=True)
    p.add_argument('--expected-uuid', required=True)
    args = p.parse_args()
    try:
        data = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        identity = Path(args.identity).read_text(encoding='utf-8')
        result = validate(data, identity, args.expected_host, args.expected_uuid)
        print(json.dumps(result, sort_keys=True, indent=2))
    except (OSError, UnicodeError, ValueError, ValidationError, TypeError, KeyError) as exc:
        print(f'VALIDATION FAILED: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
