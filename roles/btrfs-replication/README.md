# btrfs-replication — native Btrfs replication (0034/0035/0040)

## Current production arrangement — 7 November 2026

`mars` initiates incremental read-only snapshot replication to `backup`.
The active service is named `btrfs-native-push.service` for continuity, but
runs the **simplified agreed-parent** executable rather than the retired legacy
`btrfs-native-push --latest` implementation.

- Source: `/media/usb/@snapshots/@data/YYYYMMDD-HHmmssZ` on `mars`.
- Receiver: `/@data/mars-received/@data/YYYYMMDD-HHmmssZ` on `backup`.
- Sender command: `/usr/local/bin/btrfs-simplified-replication sender cycle`.
- Sender schedule: `btrfs-native-push.timer`, **03:30 UTC daily** on `mars`.
- Receiver retention manager: `/usr/local/sbin/btrfs-snapshot-manager`.
- Receiver pruning: `btrfs-receiver-simple-prune.timer`, **04:15 UTC daily**
  on `backup`, maximum **10** deletions per invocation.
- Source and receiver independently retain `parent` and `prior` in their
  root-owned `.simple-agreed-parent.json` records. Current and prior parents
  are protected against snapshot pruning at both ends.
- Existing independent checkpoint holds and legacy receipt evidence are retained.
  Legacy receipts do **not** permanently pin the associated snapshots; the
  shared retention buckets determine expiry subject to protected parents/holds.

The simplified sender chooses the **newest eligible snapshot** newer than the
agreed parent, and transfers at most one per invocation. The receiver confirms
Btrfs identity before state advancement; a lost acknowledgement can be
reconciled without repeating an already completed transfer. This is a latest
recovery-point policy, not a requirement to replicate every hourly snapshot.

The first unattended simplified replication run succeeded on **7 November
2026** at 03:30 UTC. Receiver pruning was explicitly authorised and activated
on **7 November 2026** with the limits above. Its first unattended execution,
scheduled for **8 November 2026**, remains the Step 12 operational acceptance
gate as of this documentation update. Do not describe that first execution as
passed until its systemd/journal and parent-state evidence is reviewed.

## Effective inventory and deployment

Role defaults deliberately leave activation **off**. The production values
are supplied by Ansible inventory, including the host-specific settings:

| Setting | `mars` | `backup` |
| --- | --- | --- |
| `btrfs_native_push_schedule_enabled` | `true` | `false` |
| `btrfs_simplified_replication_install_enabled` | `true` | `true` |
| `btrfs_simplified_replication_active_enabled` | `true` | `false` |
| `btrfs_simplified_receiver_retention_install_enabled` | not enabled | `true` |
| `btrfs_simplified_receiver_prune_enabled` | not enabled | `true` |

On `backup`, the receiver pruning calendar is `*-*-* 04:15:00 UTC` and
`btrfs_simplified_receiver_prune_max_delete` is `10`.
Review effective variables with `ansible-inventory --host mars` and
`ansible-inventory --host backup` before changing or deploying anything;
role defaults do not prove the live host's state.

From `/home/richard/playbooks` on `mango`, accepted targeted checks use
`ansible-playbook btrfs-replication.yaml --limit 'mars,backup' --check --diff
--tags 'scheduling,simplified-agreed-parent,simplified-receiver-retention'
--vault-password-file ~/.vault_pass.txt`. Inspect reported changes; a
check-mode run does not perform a pruning invocation or a replication cycle.
Do not change the deletion gate or retention schedule outside explicit change
control and operator authorisation.

## Legacy implementation retired (0042)

The native-push/receiver executable source and staged intermediate agreed-parent
modules are retired from the operational role. Historical implementation,
verification and rollback records remain in the Diaries 0040-FEAT feature and
Git history. No Ansible task recreates the old privileged receiver endpoint,
legacy sudoers policy or pre-simplified sender. The existing
`btrfs-native-push.service` and `.timer` **remain active unit names** but
always run the simplified executable as root. The receiver uses its existing
`btrfs-receiver-simple-prune` units, shared manager, and guarded parent state.

The 0039 qgroup-maintenance tasks are separate and remain installed. Source
retirement does not remove installed host files a second time; accepted 0040
host-retirement evidence must be checked before any new destructive host action.

## 0045 task organisation

`btrfs-replication.yaml` explicitly loads `tasks_from: native.yaml`. The native
entry point now statically imports ordered, endpoint-guarded phases. It does
not use the default role `main.yaml`: that path remains the generic snapshots
dispatch used by `snapshots.yaml` to fail closed on the receiver. Per-task
tags, conditions, handler ordering and installed files are unchanged.
