# 0045 Step 2 — Managed source-to-installation map

This is a *review guide*, not a new Ansible installation manifest. Each managed
asset retains the original installation module, path, owner, mode, guards and task
order in its phase file. Do not bulk synchronize entire source trees or clean
backup datasets. Reference the definitive v2 baseline for post-deployment comparison.

## Snapshot role

| Role phase | Source asset and installed target |
|---|---|
| `installed-files.yaml` | `btrfs-snapshot-manager.py` → `btrfs_snapshot_manager_path` |
| `installed-files.yaml` | `diaries-backup-history.py` → `btrfs_snapshot_history_path` |
| `installed-files.yaml` | `btrfs-extent-sharing.py` → `btrfs_snapshot_extent_tool_path` |
| `installed-files.yaml` | `roles/diaries/files/sync/scripts/complete-dataset-manifest.py` → `btrfs_snapshot_manifest_tool_path` |
| `state-and-config.yaml` | existing `.checkpoint-holds.json` retained (`force: false`), manager JSON template → `btrfs_snapshot_manager_config_path` |
| `systemd-units.yaml` | `btrfs-snapshot-{create,prune}.{service,timer}` rendered to `/etc/systemd/system/` |

## Native replication role

| Role phase | Installation / contract |
|---|---|
| `endpoint-setup.yaml` | source snapshot manager + protected config; receiver parent and transaction state |
| `receiver-holds.yaml` | validate existing receiver holds and mandatory receipt identities; never reset holds |
| `receiver-config.yaml` | receiver config / lock; opt-in guards retained |
| `retire-legacy-pull.yaml` | only the *existing two* obsolete pull executables kept absent |
| `source-scheduling.yaml` | source `btrfs-native-push.{service,timer}`, legacy transport guard and activation |
| `receiver-policy.yaml` | receiver retention policy and retired observer sudoers |
| `simplified-runtime.yaml` | agreed-parent command and backup status tool |
| `receiver-retention.yaml` | shared manager, receiver config, prune units and timer activation |
| `qgroup-maintenance.yaml` | existing endpoint-neutral `qgroup-maintenance.yaml` tasks |

The `local-backup` role retains existing `synchronize` options excluding Python
bytecode. **Do not delete** `/root/scripts/backup/remote/` on `mars` as a result
of retiring an Ansible operator entry point. Run role/task-map tests and compare
static host manifests *after* authorised normal Ansible apply.
