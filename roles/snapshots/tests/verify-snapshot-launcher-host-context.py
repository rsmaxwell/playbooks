#!/usr/bin/env python3
"""0039-DEF source-only guards for safe host-context snapshot deployment."""
from pathlib import Path

root = Path(__file__).resolve().parents[3]
launcher = (root / 'scripts/snapshots.sh').read_text()
play = (root / 'snapshots.yaml').read_text()
local = (root / 'roles/backup-collection/tasks/main.yaml').read_text()
remote = (root / 'roles/btrfs-replication/tasks/main.yaml').read_text()

assert '- hosts: local_backup' in play and '- role: backup-collection' in play
assert '- hosts: remote_backup' in play and '- role: btrfs-replication' in play
assert '- role: snapshots' not in play  # no bypass of host-specific configuration
assert '--limit "$host"' in launcher
assert '--tags snapshots' in launcher
assert '--vault-password-file "$HOME/.vault_pass.txt"' in launcher
assert 'args+=(--check --diff)' in launcher
assert 'args+=(--diff)' in launcher
assert 'mode="check"' in launcher
assert 'mode_seen=true' in launcher and 'host_seen=true' in launcher
assert 'btrfs_snapshot_require_verified_diaries:' in local
assert 'btrfs_snapshot_writer_lock_path:' in local
assert 'btrfs_snapshot_diaries_relative_path:' in local
assert 'btrfs_snapshot_diaries_marker_relative_path:' in local
assert 'btrfs_snapshot_retire_legacy_snapper_timers' not in remote
print('PASS: snapshots launcher is check-only by default and uses host-specific snapshot role context')
