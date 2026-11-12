# Native Btrfs snapshot manager

This role is the 0035 native timestamp-named Btrfs snapshot manager used by `mars` and `backup`. It owns only the configured `@snapshots` namespace and does not manage retired numeric legacy snapshots.

## Safe deployment / activation split

Ordinary role execution installs prerequisites, the manager, `diaries-backup-history`, schema-2 verifier, configuration and systemd unit files, then runs read-only `status` preflight. It does **not** enable native timers :

```yaml
btrfs_snapshot_activation_enabled: false
```

Activation is explicitly gated by `btrfs_snapshot_activation_enabled`.

## Managed layout and complete timestamp sets

For a filesystem mounted at `/media/usb`:

```text
/media/usb/@snapshots/
├── root/
│   └── 20261009-170000Z
└── @data/
    └── 20261009-170000Z
```

For a filesystem rooted at `/` the equivalent root is `/@snapshots`. `@snapshots` is a Btrfs subvolume, while each timestamp entry is a read-only snapshot.

One create invocation uses one UTC timestamp for **all** configured sources. Retention is evaluated over complete timestamp sets, not independently per source. If a timestamp is present for only some configured sources, pruning fails closed until the partial set is investigated.

## Verified Diaries snapshot barrier

0034/0035 integration can enable:

- a shared whole-backup `writer_lock_path`;
- a configured snapshot source (normally `@data`);
- the fixed Diaries dataset relative path (normally `backup/pluto/diaries-backup`); and
- a receiver-written verification marker (normally `backup/.diaries-snapshot-verified.json`).

The receiving job takes the writer lock exclusively while it mutates the writable mirror. Snapshot creation takes the same lock shared/non-blocking. Before `create`, the manager also requires the marker to be `snapshotEligible=true` and verifies its logical dataset, `backupId` and manifest SHA-256 against the current fixed dataset. A missing, stale or mismatched marker blocks snapshot creation.

The marker is evidence that the receiver already ran the independent schema-2 verifier; the manager does not rehash the entire Files tree on every hourly snapshot.

## Retention

The default GFS-style policy is:

```text
hourly  48
daily   14
weekly  12
monthly 24
yearly   5
minimum age before pruning: 30 minutes
```

A timestamp can satisfy more than one bucket. The newest complete timestamp set is always retained.

## Operator commands

```bash
sudo btrfs-snapshot-manager status
sudo btrfs-snapshot-manager list
sudo btrfs-snapshot-manager create
sudo btrfs-snapshot-manager prune --dry-run
sudo btrfs-snapshot-manager prune
```

`status` is non-mutating and reports whether the current Diaries verification marker is valid. `create` refuses to run when the writer lock is busy or the current Diaries state is not verified.

The read-only history tool is:

```bash
sudo diaries-backup-history list
sudo diaries-backup-history list --all
sudo diaries-backup-history show BACKUP_ID
sudo diaries-backup-history path BACKUP_ID
sudo diaries-backup-history verify BACKUP_ID
```

`list` groups by `(logicalDataset, backupId)`, so the same Diaries ID retained by several whole-backup snapshots is shown once with an occurrence count. `list --all` exposes each timestamp occurrence. A repeated identity with different manifest hashes is reported as a conflict. Paths are accepted only when the fixed dataset resolves inside the manager-owned snapshot occurrence.

## Safety boundaries

- only timestamp names matching UTC `YYYYMMDD-HHmmssZ` below `snapshot_root` are manager-owned;
- sources and snapshot repository must be on the same Btrfs filesystem;
- snapshot sources must be Btrfs subvolumes and snapshots are read-only;
- multi-source create failure rolls back only snapshots created by that invocation;
- retention refuses incomplete multi-source timestamp sets;
- receiver/snapshot concurrency is controlled by the common writer lock;
- verified Diaries marker mismatch blocks snapshot creation;
- normal Playbooks deployment is non-activating;
- no history command restores, prunes or deletes anything.

### Legacy retirement status

Legacy Snapper was retired through the 0040-FEAT one-off migration. The native role does not install or manage Snapper or `btrfs-legacy-prune` units. Historical migration instructions remain in the change-control evidence.

The read-only `btrfs-snapshot-manager status` command also emits qgroup totals,
stale and under-deletion counts, plus `qgroups_status=ok|warning|unavailable`.
The qgroup query is bounded to 8 seconds and cannot trigger cleanup or quota
rescan. A query error leaves normal status behaviour intact. Warnings appear
when stale records exceed 100 or any under-deletion entries are reported.


## 0039-DEF native prune identity diagnostics (source change, deployment pending)

Native `prune` logs `DELETE <source> <timestamp> subvol_id=<id> <path>`
immediately before each individual `btrfs subvolume delete`. The ID comes
from a read-only `btrfs subvolume show` on the exact candidate path and must
parse uniquely; if identity lookup fails, pruning aborts rather than recording
a misleading identity. The existing retention, checkpoint-hold and replication
protections remain unchanged. Dry-run still prints `WOULD-DELETE` and performs
no additional identity lookup. This diagnostic does **not** remove qgroups or
change quota configuration. Use the naturally scheduled deletion journal and
subsequent `btrfs qgroup show -pcre` to correlate exact IDs after deployment.

## 0040-FEAT Step 13: bounded source catch-up pruning (8 November 2026)

The source `prune` CLI accepts optional `--max-delete 1..32` (0043-FEAT). The legacy
uncapped invocation and `run` subcommand retain their prior behaviour.
Scheduled pruning uses `--max-delete {{ btrfs_snapshot_prune_max_delete }}`
(default 10, overridden to 32 by the central Ansible inventory on `mars`); the manager still validates the **entire** deletion candidate
set and the checkpoint/replication parent protections before deleting any
selected snapshot, and uses the established manager lock.

`btrfs_snapshot_prune_activation_enabled` defaults to `false` independently
of `btrfs_snapshot_activation_enabled`. When native source scheduling is active,
Ansible **stops and disables** the source prune timer until explicitly approved,
including clearing a stale enabled-but-inactive timer that would start after
reboot. Snapshot creation remains active. With explicit `true` approval,
Ansible starts and enables the prune timer. Installation of the capped manager
and service definition is therefore safe without immediately deleting snapshots.
The `mars` prune timer must be deliberately enabled through managed Ansible
settings **only after** approval of the read-only deletion plan.
The first schedule activation may occur immediately due to `Persistent=true`.
Monitor the journal, retention count and qgroup status during catch-up.
Do not use the uncapped manual command for the 204-set catch-up.

## 0043-FEAT: daily source pruning with central inventory

The source and receiver prune timers are both scheduled for 04:15 UTC daily
through `/etc/ansible/group_vars/all/btrfs-maintenance-schedule.yaml`
(the authoritative inventory lives under `/etc/ansible` on
`mango`, not in the Playbooks Git repository). Snapshot creation remains hourly. The guarded source prune cap
is 32 complete timestamp sets per daily run; the receiver keeps its existing
independent 10-snapshot cap. This cap increase is required because hourly
creation can generate approximately 24 expired hourly snapshots per day.
A daily prune usually finishes scheduling deletions quickly, but Btrfs
reclaims blocks asynchronously. 04:15 source and receiver pruning is safe
under their independent per-filesystem locks and agreed-parent protections.
Do not interpret an exited pruning service as completed block reclamation.

The source cap still validates all eligible candidates before deleting any,
and refuses missing/unsafe identities, incomplete sets, checkpoint holds or
protected replication parents. A catch-up prune can delete up to 32 eligible
sets, subject to the configured retention policy. `Persistent=true` on the
source timer can cause a missed daily run to fire on subsequent startup.
See the [repository README](../../README.md#btrfs-maintenance-schedules) for installation,
verification and rollback of the central schedule.

## 0045 task organisation

The role default task entry point now statically imports its existing tasks
into ordered validation, prerequisites, source roots, installed files, state,
unit configuration, preflight and activation phases. Per-task tags, conditions,
notification/handler ordering and installed file destinations are unchanged.
