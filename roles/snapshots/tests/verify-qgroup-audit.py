#!/usr/bin/env python3
"""Offline fixtures, never invokes Btrfs."""
import importlib.util
from pathlib import Path

p = Path(__file__).resolve().parents[1] / 'files' / 'btrfs-qgroup-audit.py'
spec = importlib.util.spec_from_file_location('btrfs_audit', p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

header_old = 'qgroupid rfer excl max_rfer max_excl parent child\n-------- ---- ---- -------- -------- ------ -----\n'
header_new = 'Qgroupid Referenced Exclusive max_rfer max_excl parent child\n-------- ---------- --------- -------- -------- ------ -----\n'
header_mars = ('Qgroupid    Referenced    Exclusive  Max referenced  Max exclusive Parent   Child   Path\n'
               '--------    ----------    ---------  --------------  ------------- ------   -----   ----\n')
sub = 'ID 275 gen 12 top level 5 path @data\nID 300 gen 13 top level 5 path @snapshots/x\n'
pending = 'ID 399 gen 14 top level 5 path @snapshots/deleting\n'
rows = ('0/275 1.00GiB 0.00B none none --- ---\n'
        '0/300 1.00GiB 0.00B none none --- ---\n'
        '0/399 0.00B 0.00B none none --- ---\n'
        '0/400 0.00B 0.00B 1.00TiB none --- ---\n'
        '0/401 0.00B 0.00B none none 1/2 ---\n'
        '0/402 0.00B 0.00B none none --- --- <stale>\n'
        '1/2 0.00B 0.00B none none --- ---\n')
for hdr in (header_old, header_new, header_mars):
    got = m.reconcile(sub, sub, hdr + rows, pending)
    assert got['counts'] == {'active': 2, 'pending-deletion': 1,
                              'limited-protected': 1, 'related-protected': 1,
                              'unmatched-candidate': 1, 'higher-level': 1}, got
    assert got['deletion_authorized'] is False
    print('PASS: version-compatible conservative classification')

def fails(fn):
    try:
        fn()
    except m.AuditError:
        print('PASS: failed closed')
    else:
        raise AssertionError('expected AuditError')

fails(lambda: m.reconcile(sub, sub + 'ID 401 gen 15 top level 5 path new\n', header_old + rows, pending))
fails(lambda: m.reconcile(sub, sub, 'garbage\n' + rows, pending))
fails(lambda: m.reconcile(sub, sub, header_old + rows.replace('1/2 ---', '<strange> ---'), pending))
fails(lambda: m.reconcile(sub, sub, header_old + rows.replace('0/401', '0/275'), pending))
large = header_old + ''.join(f'0/{i} 0.00B 0.00B none none --- ---\n' for i in range(1000, 32001))
got = m.reconcile(sub, sub, large, '')
assert got['qgroup_count'] == 31001
assert got['counts']['unmatched-candidate'] == 31001
assert len(got['review_sample']) == 20
print('PASS: 31,001-record bounded report')

# Actual btrfs-progs 6.6.3 data format on mars, including a pathname and
# a stale qgroup with a retained 3.64TiB limit. Source fixture only.
mars_rows = ('0/260 325.63GiB 16.00KiB 3.64TiB none - - @data\n'
             '0/20919 0.00B 0.00B none none - - <stale>\n'
             '0/20920 0.00B 0.00B 3.64TiB none - - <stale>\n')
mars_sub = 'ID 260 gen 61362 top level 5 path @data\n'
mars_result = m.reconcile(mars_sub, mars_sub, header_mars + mars_rows, '')
assert mars_result['counts'] == {
    'active': 1, 'unmatched-candidate': 1, 'limited-protected': 1}, mars_result
assert mars_result['deletion_authorized'] is False
print('PASS: real mars multiword header, path and retained limit')

fails(lambda: m.reconcile(mars_sub, mars_sub,
                          header_mars.replace('Max exclusive', 'Max something') + mars_rows, ''))
print('PASS: unknown multiword heading fails closed')

# Complete output retains every record, subvolume path and quota limit.
full = m.reconcile(sub, sub, header_old + rows, pending, full_manifest=True,
                   inspect_ids=['0/400', '0/402', '0/999'])
assert full['manifest']['qgroups'] and len(full['manifest']['qgroups']) == 7
assert len(full['manifest']['active_subvolumes']) == 2
assert len(full['manifest']['pending_subvolumes']) == 1
assert full['inspected_qgroups']['0/400']['max_rfer'] == '1.00TiB'
assert full['inspected_qgroups']['0/402']['annotation'] == '<stale>'
assert full['inspected_qgroups']['0/999'] is None
assert full['fingerprint_sha256'] == m.reconcile(sub, sub, header_old + rows, pending)['fingerprint_sha256']
assert full['deletion_authorized'] is False
print('PASS: full manifest and targeted ID lookup preserve all evidence')

# Large manifest never silently truncates row-level evidence.
full_large = m.reconcile(sub, sub, large, '', full_manifest=True)
assert len(full_large['manifest']['qgroups']) == 31001
assert len(full_large['review_sample']) == 20
print('PASS: full 31,001-record export with bounded summary')
