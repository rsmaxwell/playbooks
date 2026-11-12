#!/usr/bin/env python3
"""Offline 0034 Step 11.4 unattended-operating source contract checks."""
from pathlib import Path
import ast

root = Path(__file__).resolve().parents[2]

def read(rel):
    return (root / rel).read_text(encoding='utf-8')

def check(value, message):
    if not value:
        raise AssertionError(message)
    print('PASS: ' + message)

# pluto: complete backup publication timer is source-owned and default-off.
diaries_defaults = read('roles/diaries/defaults/main.yaml')
diaries_tasks = read('roles/diaries/tasks/unattended-backup.yaml')
diaries_service = read('roles/diaries/templates/etc/systemd/system/diaries-complete-backup-publish.service.j2')
check('diaries_complete_backup_schedule_enabled: false' in diaries_defaults,
      'pluto complete-backup scheduling is default-off')
check('diaries-complete-backup-publish.timer' in diaries_tasks and 'enabled:' in diaries_tasks,
      'pluto role owns explicit systemd schedule state')
check('backup-dataset.sh publish-preflight' in diaries_service and 'backup-dataset.sh publish' in diaries_service,
      'scheduled pluto job performs preflight then supported atomic publication')

# mars: verified pull timer is default-off and remains under the whole-backup lock contract.
local_defaults = read('roles/local-backup/defaults/main.yaml')
pull_tasks = read('roles/local-backup/tasks/diaries_pull.yaml')
root_wrapper = read('roles/local-backup/templates/backup-machine/backup.sh.j2')
check('diaries_pull_schedule_enabled: false' in local_defaults,
      'mars Diaries pull scheduling is default-off')
check('diaries-pull.timer' in pull_tasks and 'diaries_snapshot_integration_enabled | bool' in pull_tasks,
      'scheduled mars pull requires verified snapshot integration')
check('Disable stale unattended receive timer when helper is not installed' in pull_tasks,
      'disabling the pull helper also disables an already-installed timer')
check('legacy_remote_rsync_push_enabled: true' in local_defaults and
      'legacy_remote_rsync_push_enabled | bool' in root_wrapper,
      'historical rsync push is retained only behind an explicit rollback switch')

# mars -> backup: native timer uses incremental-only latest selection and refuses dual transport.
remote_defaults = read('roles/btrfs-replication/defaults/main.yaml')
remote_tasks = read('roles/btrfs-replication/tasks/native.yaml')
push_source = read('roles/btrfs-replication/files/btrfs-native-push.py')
endpoint_source = read('roles/btrfs-replication/files/btrfs-native-endpoint.py')
ast.parse(push_source)
ast.parse(endpoint_source)
check('btrfs_native_push_schedule_enabled: false' in remote_defaults,
      'native off-site push scheduling is default-off')
check('btrfs-native-push.timer' in remote_tasks and 'Refuse dual off-site transports' in remote_tasks,
      'native timer activation is source-owned and rejects the rendered legacy rsync phase')
check("selection.add_argument('--latest'" in push_source and 'already-accepted' in push_source,
      'unattended push selects newest snapshot idempotently')
check('accepted common parent' in push_source and '--latest is incremental-only' in push_source,
      'unattended push never creates an implicit full reseed')
check("--role', 'list-source'" in push_source and 'def list_source' in endpoint_source,
      'latest selection uses the constrained privileged endpoint rather than broad root shell access')

# The three default calendars leave an hourly snapshot boundary between pull and push.
check('00:30:00 UTC' in diaries_defaults and '01:30:00 UTC' in local_defaults and '03:30:00 UTC' in remote_defaults,
      'default-off calendars establish publish -> pull -> hourly snapshot -> push ordering')

print('PASS: 0034 Step 11.4 source contract verified')
