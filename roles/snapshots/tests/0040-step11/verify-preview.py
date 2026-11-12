#!/usr/bin/env python3
"""Offline regression for 0040 Step 11 one-time hold preview."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile

script = Path(__file__).with_name('preview-checkpoint-hold-migration.py')
spec = importlib.util.spec_from_loader('preview', SourceFileLoader('preview', str(script)))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    doc = {'schema': 1, 'holds': {}}
    truth = {}
    for index, (stamp, reason) in enumerate(m.EXPECTED.items()):
        ids = {'root': f'0000000{index}-0000-0000-0000-000000000001', '@data': f'0000000{index}-0000-0000-0000-000000000002'}
        doc['holds'][stamp] = {'reason': reason, 'source_uuids': ids}
        for name, uuid in ids.items():
            p = root / name / stamp
            p.mkdir(parents=True)
            truth[p] = uuid
    lookup = lambda p: truth[p]
    result = m.preview(doc, lookup, root)
    assert set(result['holds']) == set(m.EXPECTED)
    assert all(set(v['source_uuids']) == {'@data'} for v in result['holds'].values())
    print('PASS: valid migration preview preserves reasons and @data UUIDs')
    import copy
    def refused(bad, resolver=lookup):
        try:
            m.preview(bad, resolver, root)
        except m.UnsafeState:
            return
        raise AssertionError('unsafe state accepted')
    for mutation in ['schema', 'reason', 'extra', 'uuid', 'timestamp']:
        bad = copy.deepcopy(doc)
        stamp = next(iter(m.EXPECTED))
        if mutation == 'schema': bad['schema'] = 2
        elif mutation == 'reason': bad['holds'][stamp]['reason'] = 'changed'
        elif mutation == 'extra': bad['holds'][stamp]['source_uuids']['other'] = bad['holds'][stamp]['source_uuids']['root']
        elif mutation == 'uuid': bad['holds'][stamp]['source_uuids']['@data'] = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        else: bad['holds']['20260101-000000Z'] = bad['holds'][stamp]
        refused(bad)
    print('PASS: schema, reason, source, UUID, and timestamp deviations fail closed')
    gone = next(iter(truth))
    gone.rmdir()
    refused(doc)
    print('PASS: missing snapshot fails closed')
print('PASS: 0040 Step 11 preview regression')
