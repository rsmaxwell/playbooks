#!/usr/bin/env python3
"""Offline, nonmutating test of qgroup safety assessment."""
import copy
import importlib.util
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'files'
def load(n, p):
    spec = importlib.util.spec_from_file_location(n, root / p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
assessment = load('assessor', 'assess-qgroup-safety.py')
audit = load('audit', 'btrfs-qgroup-audit.py')
validate = load('validator', 'validate-qgroup-manifest.py')
header = 'qgroupid rfer excl max_rfer max_excl parent child\n-------- ---- ---- -------- -------- ------ -----\n'
rows = ('0/5 1.00GiB 1.00MiB none none --- ---\n'
        '0/275 1.00GiB 1.00MiB 1.00TiB none --- ---\n'
        '0/300 1.00GiB 0.00B none none --- ---\n'
        '0/301 0.00B 0.00B none none --- ---\n'
        '0/302 0.00B 0.00B 1.00TiB none --- ---\n'
        '0/303 0.00B 0.00B none none 1/1 ---\n'
        '1/1 0.00B 0.00B none none --- ---\n')
sub = 'ID 275 gen 3 top level 5 path @data\nID 300 gen 3 top level 5 path @snapshots/test\n'
data = audit.reconcile(sub, sub, header + rows, '', full_manifest=True)
data['filesystem'] = '/'
identity = '''=== Host and capture time ===
backup
2026-10-21T12:10:32+00:00
=== Filesystem identity ===
Label: none  uuid: b915f967-7cb4-4c14-b11b-f52209637a22
=== Mount identity ===
TARGET SOURCE FSTYPE OPTIONS
/ /dev/sda2 btrfs rw,subvolid=5,subvol=/
=== Quota rescan status ===
no rescan operation in progress
'''
uuid = 'b915f967-7cb4-4c14-b11b-f52209637a22'
result = assessment.assess(data, identity, 'backup', uuid, [300])
assert result['counts']['active-protected-snapshot'] == 1
assert result['counts']['unmatched-investigation-only'] == 1
assert result['counts']['limited-excluded'] == 1
assert result['counts']['related-excluded'] == 1
assert result['counts']['higher-level-excluded'] == 1
assert result['deletion_authorized'] is False and result['deletion_commands'] == []
print('PASS: conservative offline assessment, no deletion authorisation')
for protected in ([], [301], [300,300], [0]):
    try:
        assessment.assess(data, identity, 'backup', uuid, protected)
    except assessment.ValidationError:
        pass
    else:
        raise AssertionError(f'accepted unsafe protected IDs {protected}')
changed = copy.deepcopy(data)
changed['fingerprint_sha256'] = '0'*64
try:
    assessment.assess(changed, identity, 'backup', uuid, [300])
except assessment.ValidationError:
    pass
else:
    raise AssertionError('accepted tampered manifest')
print('PASS: missing/incorrect protection and manifest corruption fail closed')
bigrows = header + '0/300 0.00B 0.00B none none --- ---\n' + ''.join(
    f'0/{n} 0.00B 0.00B none none --- ---\n' for n in range(1000,32001))
big = audit.reconcile('ID 300 gen 3 top level 5 path x\n', 'ID 300 gen 3 top level 5 path x\n', bigrows, '', full_manifest=True)
big['filesystem'] = '/'
out = assessment.assess(big, identity, 'backup', uuid, [300])
assert out['qgroups'] == 31002 and len(out['investigation_sample']) == 20
assert out['counts']['unmatched-investigation-only'] == 31001
print('PASS: 31,002-record bounded assessment')
