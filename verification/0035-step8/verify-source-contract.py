#!/usr/bin/env python3
from pathlib import Path
p=Path(__file__).with_name('verify-acceptance.yaml').read_text()
for x in ('hosts: mars','hosts: backup','hosts: pluto','changed_when: false','--host mars dry-run','--host pluto dry-run','received_uuid','checkpoint-holds.json','btrfs-snapshot-create.timer','/usr/local/sbin/diaries-backup-history'):
    assert x in p,x
for x in ('--apply','btrfs subvolume delete','btrfs receive','btrfs send'):
    assert x not in p,x
print('PASS: Step 8 inventory is read-only and covers three-host guardrails')
