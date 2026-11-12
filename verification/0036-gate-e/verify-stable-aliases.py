#!/usr/bin/env python3
"""Read-only source regression for 0036 Gate E compatibility aliases."""
from pathlib import Path
import sys
r=Path(__file__).resolve().parents[2]
def read(rel): return (r/rel).read_text()
d=read('roles/diaries/defaults/main.yaml')
legacy=['diaries_0036_fixed_capture_enabled','diaries_0036_host_nas_mount_enabled','diaries_0036_host_nas_mount_root','diaries_0036_host_nas_host','diaries_0036_host_nas_share','diaries_0036_host_nas_content_path','diaries_0036_host_nas_username','diaries_0036_host_nas_password']
for a in legacy:
 b=a.replace('diaries_0036_', 'diaries_')
 assert f'{a}:' in d and f'{b}: "{{{{ {a} }}}}"' in d,(a,b)
for rel in ['roles/diaries/tasks/main.yaml','roles/diaries/tasks/0036-host-nas-mount.yaml','roles/diaries/templates/0036-nas-credentials.j2','roles/diaries/templates/.env.j2','roles/diaries/templates/etc/systemd/system/diaries-complete-backup-publish.service.j2']:
 assert 'diaries_0036_' not in read(rel),rel
service=read('roles/diaries/templates/etc/systemd/system/diaries-complete-backup-publish.service.j2')
assert '{% if diaries_fixed_capture_enabled | bool %}' in service
assert 'fixed-capture-preflight' in service and 'fixed-capture' in service
assert 'publish-preflight' in service and 'publish' in service
runtime=read('roles/diaries/templates/.env.j2')
for k in ['DIARIES_0036_FIXED_CAPTURE_ENABLED','DIARIES_0036_HOST_MOUNT_ROOT','DIARIES_0036_HOST_FILES_ROOT','DIARIES_0036_HOST_FILES_IDENTITY']:
 assert k+'=' in runtime
mount=read('roles/diaries/tasks/0036-host-nas-mount.yaml')
assert '/etc/diaries/0036-nas-credentials' in mount
print('PASS: Gate E stable Ansible aliases preserve 0036 runtime and rollback contracts')
