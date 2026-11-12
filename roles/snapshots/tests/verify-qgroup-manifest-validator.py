#!/usr/bin/env python3
"""Offline regression for manifest validator; no Btrfs or network access."""
import copy
import importlib.util
from pathlib import Path

root = Path(__file__).resolve().parents[1] / 'files'

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, root / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

audit = load('audit', 'btrfs-qgroup-audit.py')
check = load('validate', 'validate-qgroup-manifest.py')
header = 'qgroupid rfer excl max_rfer max_excl parent child\n-------- ---- ---- -------- -------- ------ -----\n'
rows = ('0/5 1.00GiB 1.00MiB none none --- ---\n'
        '0/275 1.00GiB 1.00MiB 1.00TiB none --- ---\n'
        '0/300 0.00B 0.00B none none --- ---\n'
        '0/301 0.00B 0.00B 1.00TiB none --- ---\n'
        '0/302 0.00B 0.00B none none --- --- <stale>\n')
sub = 'ID 275 gen 2 top level 5 path @data\n'
manifest = audit.reconcile(sub, sub, header + rows, '', full_manifest=True, inspect_ids=['0/302'])
manifest['filesystem'] = '/'
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
UUID = 'b915f967-7cb4-4c14-b11b-f52209637a22'
assert check.validate(manifest, identity, 'backup', UUID)['qgroups'] == 5
print('PASS: correct manifest, fingerprint and filesystem identity')

def reject(changed, evidence=identity, uuid=UUID):
    try:
        check.validate(changed, evidence, 'backup', uuid)
    except check.ValidationError:
        return
    raise AssertionError('expected conservative validation failure')

for edit in (
    lambda m: m['manifest']['qgroups'].append(copy.deepcopy(m['manifest']['qgroups'][0])),
    lambda m: m['manifest']['qgroups'][2].update(category='active'),
    lambda m: m['manifest']['qgroups'][2].update(max_rfer='1.00TiB'),
    lambda m: m.update(fingerprint_sha256='0' * 64),
    lambda m: m.update(qgroup_count=4),
    lambda m: m.update(deletion_authorized=True),
    lambda m: m['manifest']['active_subvolumes'].append({'id':275, 'path':'duplicate'}),
    lambda m: m['review_sample'].clear(),
):
    changed = copy.deepcopy(manifest)
    edit(changed)
    reject(changed)
print('PASS: duplicate, classification, fingerprint, safety and sample tampering fail closed')
reject(manifest, identity.replace('no rescan operation in progress', 'rescan running'))
reject(manifest, identity.replace('subvolid=5', 'subvolid=275'))
reject(manifest, identity.replace('b915f967', 'a915f967'))
reject(manifest, uuid='00000000-0000-0000-0000-000000000000')
print('PASS: filesystem identity, quota rescan and UUID mismatches fail closed')

big = header + ''.join(f'0/{sid} 0.00B 0.00B none none --- ---\n' for sid in range(1000, 32001))
large = audit.reconcile('', '', big, '', full_manifest=True)
large['filesystem'] = '/'
assert check.validate(large, identity, 'backup', UUID)['qgroups'] == 31001
print('PASS: 31,001-record full offline verification')
