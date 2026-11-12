#!/usr/bin/env python3
"""0047 source-only contract: a single collection role, preserved endpoint routing."""
from pathlib import Path
import yaml

root = Path(__file__).resolve().parents[3]
collection = yaml.safe_load((root / 'backup-collection.yaml').read_text())
snapshots = yaml.safe_load((root / 'snapshots.yaml').read_text())
native = yaml.safe_load((root / 'btrfs-replication.yaml').read_text())
assert len(collection) == 1 and collection[0]['hosts'] == 'local_backup'
assert collection[0]['roles'] == [{'role':'backup-collection'}]
assert snapshots[0]['hosts'] == 'local_backup'
assert snapshots[0]['roles'] == [{'role':'backup-collection'}]
assert snapshots[1]['hosts'] == 'remote_backup'
assert snapshots[1]['roles'] == [{'role':'btrfs-replication'}]
assert native[0]['hosts'] == 'local_backup:remote_backup'
assert native[0]['tasks'][0]['ansible.builtin.include_role']['tasks_from'] == 'native.yaml'
assert (root/'roles/backup-collection/tasks/main.yaml').is_file()
assert (root/'roles/backup-collection/defaults/main.yaml').is_file()
assert not (root/'roles/local-backup').exists()
assert not (root/'roles/remote-backup').exists()
for obsolete in (
    'local-backup.yaml', 'remote-backup.yaml',
    'scripts/local-backup.sh', 'scripts/remote-backup.sh',
    'diaries-user-backup-cron.yaml',
):
    assert not (root/obsolete).exists(), obsolete
text = (root/'scripts/backup-collection.sh').read_text()
assert 'backup-collection.yaml' in text and '--check' in text and '--diff' not in text
snap_script = (root/'scripts/snapshots.sh').read_text()
assert 'snapshots.yaml' in snap_script and '--tags snapshots' in snap_script
print('PASS: only supported collection, snapshots and native replication entry points remain')
