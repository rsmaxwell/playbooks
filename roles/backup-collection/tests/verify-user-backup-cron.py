#!/usr/bin/env python3
from pathlib import Path
import yaml
root = Path(__file__).resolve().parents[3]
def load(p): return yaml.safe_load((root/p).read_text())
defaults = load('roles/backup-collection/defaults/main.yaml')
assert defaults['local_backup_user_cron_hour'] == '1'
assert defaults['local_backup_user_cron_minute'] == '45'
main = load('roles/backup-collection/tasks/install_user_scripts.yaml')
assert main[-1]['ansible.builtin.import_tasks'] == 'user_backup_cron.yaml'
cron = load('roles/backup-collection/tasks/user_backup_cron.yaml')[0]['ansible.builtin.cron']
assert cron['minute'] == '{{ local_backup_user_cron_minute }}'
assert cron['hour'] == '{{ local_backup_user_cron_hour }}'
assert cron['name'] == 'backup'
play = load('backup-collection.yaml')[0]
assert play['hosts'] == 'local_backup'
assert play['roles'] == [{'role': 'backup-collection'}]
assert not (root/'diaries-user-backup-cron.yaml').exists()
print('PASS: shared 01:45 mars cron schedule installed through permanent backup-collection role')
