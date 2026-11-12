#!/usr/bin/env python3
"""0034 Step 10 permanent mars receive/snapshot-handoff contract regression."""
import ast
from pathlib import Path
import subprocess
import tempfile
import sys

role = Path(__file__).resolve().parents[1]
helper = role / 'files/backup-machine/diaries-pull.py'
source = helper.read_text()
ast.parse(source)
assert 'flock -s ' in source and '--rsync-path=' in source
print('PASS: remote rsync holds shared pluto publisher lock')
assert "'verify', '--backup-dir'" in source and "'create', str(candidate)" in source
print('PASS: schema-2 verification precedes atomic mars receiving publication')
assert "fcntl.LOCK_EX" in source and 'repository_lock' in source
print('PASS: mars receive holds the whole-backup writer lock')
assert "'snapshotEligible': True" in source and 'atomic_marker(args.verification_marker, marker)' in source
assert source.index("'verify', '--backup-dir'") < source.index('atomic_marker(args.verification_marker, marker)')
print('PASS: snapshot eligibility is written only after independent verification and publication')
assert "'--delete'" in source and "str(incoming) + '/'" in source
print('PASS: mars pull --delete remains scoped to a private temporary incoming tree')

tasks = (role / 'tasks/diaries_pull.yaml').read_text()
defaults = (role / 'defaults/main.yaml').read_text()
main_tasks = (role / 'tasks/main.yaml').read_text()
machine_sync = (role / 'tasks/install_machine_scripts.yaml').read_text()
wrapper = (role / 'templates/diaries/diaries-pull.sh.j2').read_text()
assert 'diaries_pull_install: false' in defaults
assert 'diaries_snapshot_integration_enabled: false' in defaults
assert 'diaries_pull_schedule_enabled: false' in defaults
assert 'legacy_remote_rsync_push_enabled: true' in defaults
assert '--exclude=diaries-pull.py' in machine_sync
assert 'src: backup-machine/diaries-pull.py' in tasks
assert 'owner: "{{ ansible_user }}"' in tasks and 'group: "{{ ansible_user }}"' in tasks
assert 'src: diaries/diaries-pull.sh.j2' in tasks
for arg in ('--host', '--source-parent', '--destination-parent', '--snapshot-source-root', '--verification-marker', '--repository-lock'):
    assert arg in wrapper
assert 'diaries-pull.service' in tasks and 'diaries-pull.timer' in tasks
assert 'diaries_pull_schedule_enabled | bool' in tasks
assert 'not (diaries_pull_schedule_enabled | bool) or (diaries_snapshot_integration_enabled | bool)' in tasks
print('PASS: pull installation/scheduling are default-off, normal-user owned and gated by verified snapshot integration')
assert 'btrfs_snapshot_require_verified_diaries: "{{ diaries_snapshot_integration_enabled }}"' in main_tasks
assert 'btrfs_snapshot_writer_lock_path:' in main_tasks
print('PASS: mars snapshots role receives the same marker/lock contract only under explicit integration opt-in')
print('PASS: legacy root-copy cleanup remains explicit opt-in only')

user_wrapper = (role / 'templates/backup/backup.sh.j2').read_text()
root_wrapper = (role / 'templates/backup-machine/backup.sh.j2').read_text()
assert 'flock -x 9' in user_wrapper and 'diaries_pull_repository_lock' in user_wrapper
assert 'flock -x 9' in root_wrapper and 'diaries_pull_repository_lock' in root_wrapper
assert 'legacy_remote_rsync_push_enabled | bool' in root_wrapper
print('PASS: known mars user/root backup writers share the 0035 whole-backup lock and legacy off-site rsync is explicitly switchable')

# Existing scheduled local rsync jobs can delete only at their destination.
home = (role / 'templates/backup/home/backup.sh.j2').read_text()
root_home = (role / 'templates/backup-machine/home/backup.sh.j2').read_text()
remote = (role / 'templates/backup-machine/remote/backup.sh.j2').read_text()
assert 'location="/media/usb/@data/backup/mars"' in home
assert 'location="/media/usb/@data/backup/mars"' in root_home
assert '/media/usb/@data/backup${source}/ ${host}:${dest}' in remote
assert '--delete --delete-excluded' in home and '--delete --delete-excluded' in root_home and '--delete --delete-excluded' in remote
print('PASS: legacy local deletes remain isolated from the mars pluto receive subtree')

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    backup = root / 'backup'
    dest = backup / 'pluto'
    dest.mkdir(parents=True)
    publisher = Path(__file__).resolve().parents[2] / 'diaries/files/sync/scripts/complete-dataset-publisher.py'
    manifest = publisher.with_name('complete-dataset-manifest.py')
    cmd = [
        sys.executable, str(helper), '--host', 'pluto',
        '--source-parent', '/home/richard/projects/diaries/data',
        '--destination-parent', str(dest), '--snapshot-source-root', str(root),
        '--verification-marker', str(backup / '.diaries-snapshot-verified.json'),
        '--repository-lock', str(backup / '.btrfs-snapshot-writer.lock'),
        '--publisher', str(publisher), '--manifest-tool', str(manifest), '--preflight',
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert not (backup / '.diaries-snapshot-verified.json').exists()
    assert not (backup / '.btrfs-snapshot-writer.lock').exists()
    assert not any(item.name.startswith('.diaries-pull-') for item in dest.iterdir())
    print('PASS: read-only mars preflight creates no marker, lock or transfer staging')
print('PASS: 0034 Step 10 mars receive source contract')
