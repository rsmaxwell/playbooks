#!/usr/bin/env python3
"""Non-invasive joint 0034/0035 Step 6 transport contract checks."""
from pathlib import Path
import ast

root = Path(__file__).resolve().parents[2]
push = (root / 'roles/btrfs-replication/files/btrfs-native-push.py').read_text()
receiver = (root / 'roles/btrfs-replication/files/btrfs-native-push-receiver.py').read_text()
endpoint = (root / 'roles/btrfs-replication/files/btrfs-native-endpoint.py').read_text()
manager = (root / 'roles/snapshots/files/btrfs-snapshot-manager.py').read_text()
sudoers = (root / 'roles/btrfs-replication/templates/btrfs-native-sudoers.j2').read_text()
for source in (push, receiver, endpoint, manager):
    ast.parse(source)
checks = {
    'mars initiates using restricted SSH operator': "'richard@10.254.22.1'" in push and "'-p', '39263'" in push,
    'sender validates source UUID and read-only state': "current.get('flags') == 'readonly'" in push and "current['uuid']" in push,
    'sender acquires exclusive push lock': 'fcntl.LOCK_EX | fcntl.LOCK_NB' in push,
    'candidate pinned before stream': push.index("local('protect-source', snapshot)") < push.index('subprocess.Popen(send'),
    'parent pinned before incremental stream': "local('protect-source', parent)" in push,
    'previous parent released only after independent receipt check': push.index("require(accepted(listing, snapshot, uuid)") < push.index("local('release-source', parent, parent_uuid)"),
    'failed sends do not release candidate': 'candidate stays protected' in push,
    'receiver accepts only previously receipted incremental parent': "old = receipt(parent)" in receiver and "Parent is not a verified accepted receiver" in receiver,
    'receiver confirms received UUID and read-only state': "received.get('received_uuid') == args.source_uuid" in receiver and "received.get('flags') == 'readonly'" in receiver,
    'receiver persists independent receipt atomically': 'os.replace(name, target)' in receiver and 'os.fsync(fd_dir)' in receiver,
    'receiver preserves failed/unaccepted destination': 'No cleanup on failure' in receiver,
    'receiver writer lock': 'fcntl.LOCK_EX | fcntl.LOCK_NB' in receiver,
    'privileged endpoint constrained by sudoers': 'NOPASSWD: /usr/local/libexec/btrfs-native-endpoint --role' in sudoers,
    'source prune honors replication pins': 'replication_protection' in manager and 'validate_prune_candidate' in manager,
    'legacy rsync marker not used in native transport': '.diaries-snapshot-verified.json' not in push + receiver,
}
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ': ' + name)
if not all(checks.values()):
    raise SystemExit(1)
print('PASS: Step 6 joint source contract')
