#!/usr/bin/env python3
"""0039-DEF offline qgroup exclusions and investigation summary.

NO deletion eligibility, commands, writes, network requests or Btrfs calls.
The protected ID list is supplied independently, is intentionally incomplete
without operator sign-off, and is never interpreted as cleanup clearance.
"""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import sys


def load_validator():
    path = Path(__file__).with_name('validate-qgroup-manifest.py')
    spec = importlib.util.spec_from_file_location('qgroup_manifest_validation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator()
ValidationError = validator.ValidationError

def assess(data, identity, host, uuid, protected_ids):
    proof = validator.validate(data, identity, host, uuid)
    if not protected_ids:
        raise validator.ValidationError('protected snapshot IDs required for assessment')
    if any(type(i) is not int or i <= 5 for i in protected_ids):
        raise validator.ValidationError('invalid protected subvolume ID')
    if len(set(protected_ids)) != len(protected_ids):
        raise validator.ValidationError('duplicate protected subvolume ID')
    active = {r['id'] for r in data['manifest']['active_subvolumes']}
    missing = sorted(set(protected_ids) - active)
    if missing:
        raise validator.ValidationError(f'protected subvolume IDs not active: {missing[:10]}')
    groups = data['manifest']['qgroups']
    qid_set = {r['id'] for r in groups}
    if any(f'0/{sid}' not in qid_set for sid in protected_ids):
        raise validator.ValidationError('protected active snapshot missing level-zero qgroup')
    buckets = Counter()
    samples = []
    for row in groups:
        category = row['category']
        if category == 'active':
            disposition = ('active-protected-snapshot' if int(row['id'].split('/')[1]) in protected_ids
                           else 'active-excluded')
        elif category == 'higher-level':
            disposition = 'higher-level-excluded'
        elif category == 'pending-deletion':
            disposition = 'pending-deletion-excluded'
        elif category == 'related-protected':
            disposition = 'related-excluded'
        elif category == 'limited-protected':
            disposition = 'limited-excluded'
        elif category == 'ambiguous':
            disposition = 'ambiguous-excluded'
        elif category == 'unmatched-candidate':
            disposition = 'unmatched-investigation-only'
        else:
            raise validator.ValidationError('unknown classification')
        buckets[disposition] += 1
        if disposition == 'unmatched-investigation-only' and len(samples) < 20:
            samples.append(row['id'])
    return {'schema': 1, 'result': 'PASS', 'assessment': 'offline-observational-only',
            'deletion_authorized': False, 'deletion_commands': [],
            'host': host, 'filesystem': proof['filesystem'], 'uuid': proof['uuid'],
            'source_fingerprint_sha256': proof['fingerprint_sha256'],
            'qgroups': len(groups), 'protected_active_subvolume_ids': sorted(protected_ids),
            'counts': dict(sorted(buckets.items())), 'investigation_sample': samples,
            'limits': ['Protected IDs supplied by operator; completeness unproven',
                       'Non-atomic historical inventory; not a live deletion preflight',
                       'Receiver receipts and holds not independently attested by this tool',
                       'No qgroup qualifies for deletion from this assessment']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--expected-host', required=True, choices=('mars', 'backup'))
    parser.add_argument('--expected-uuid', required=True)
    parser.add_argument('--protected-id', action='append', type=int, required=True)
    args = parser.parse_args()
    try:
        data = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        identity = Path(args.identity).read_text(encoding='utf-8')
        result = assess(data, identity, args.expected_host, args.expected_uuid, args.protected_id)
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        print(f'ASSESSMENT UNAVAILABLE: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
