#!/usr/bin/env python3
"""Ensure Step 7 staging gate is source-only and guards all three hosts."""
from pathlib import Path
p = Path(__file__).with_name('verify-staged.yaml').read_text()
for marker in ('hosts: mars','hosts: pluto','hosts: backup','checksum_algorithm: sha256','diaries-snapshot-cleanup','diaries-backup-history','btrfs-native-push-receiver','btrfs-snapshot-create.timer','btrfs-snapshot-prune.timer','/@data/backup','changed_when: false'):
    assert marker in p, marker
assert p.count("rstrip=False, lstrip=False") == 3, 'checksum lookup must preserve source bytes on all hosts'
assert "lookup('ansible.builtin.file', '../../' ~ item.item.source)" not in p, 'unsafe whitespace-normalizing lookup'
for forbidden in ('ansible.builtin.copy:', 'ansible.builtin.file:', 'ansible.builtin.systemd:', 'btrfs subvolume delete', 'prune --apply', 'btrfs send', 'btrfs receive'):
    assert forbidden not in p, forbidden
print('PASS: three-host staged parity, read-only guards, receiver passive and legacy safety')
