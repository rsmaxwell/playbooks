#!/usr/bin/env python3
"""Static safety check for the 0035 Step 1 read-only baseline capture."""
from pathlib import Path

root = Path(__file__).resolve().parent
playbook = (root / 'capture-baseline.yaml').read_text(encoding='utf-8')

required = [
    'hosts: pluto',
    'hosts: mars',
    'hosts: backup',
    '/media/usb/@data/backup',
    '/media/usb/@snapshots',
    '/@data/backup',
    '/@data/mars-received/@data',
    'btrfs subvolume list -u -q -R',
    'btrfs subvolume list -r -u -q -R',
    'snapper list-configs',
    'btrfs quota rescan -s /media/usb',
    'btrfs quota rescan -s /',
    'SNAPPER_INVENTORY_STATUS=INCOMPLETE',
    'SNAPPER_CONFIGS_STATUS=INCOMPLETE',
    'timeout --signal=TERM --kill-after=5s',
    'btrfs-snapshot-create.timer',
    'btrfs-snapshot-prune.timer',
    'btrfs-native-push.timer',
    'diaries-pull.timer',
    'diaries-complete-backup-publish.timer',
    '.checkpoint-holds.json',
    '.replication-protection.json',
    'btrfs-native-push-receiver --list',
    'changed_when: false',
]
for token in required:
    assert token in playbook, f'missing Step 1 contract token: {token}'

# This capture must remain observational. Adding any of these is a conscious
# Step 1 contract change and should fail review rather than silently mutate a host.
for forbidden in [
    'ansible.builtin.file:',
    'ansible.builtin.copy:',
    'ansible.builtin.template:',
    'ansible.builtin.systemd:',
    'ansible.posix.mount:',
    'btrfs subvolume create',
    'btrfs subvolume delete',
    'btrfs subvolume snapshot',
    'btrfs-snapshot-manager create',
    'btrfs-snapshot-manager prune',
    'systemctl start ',
    'systemctl stop ',
    'systemctl enable ',
    'systemctl disable ',
    'rsync -',
    'rm -',
]:
    assert forbidden not in playbook, f'mutating operation forbidden in Step 1 capture: {forbidden}'

print('PASS: 0035 Step 1 baseline capture is three-host and read-only by source contract')
