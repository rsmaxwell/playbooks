# 0034-FEAT Step 11.4 — unattended operating arrangements

Step 11.4 closes the operational gap between the accepted manual/native data path and a production arrangement that can run unattended while remaining observable and reversible.

The source changes are intentionally **default-off**. Applying the ZIP alone installs timer/service definitions but does not create a production backup, pull data, create a snapshot, push off-site data, restore anything, or enable a new timer.

## Intended ownership and default calendars

| Stage | Host | Owner | Default-off calendar |
|---|---|---|---|
| Complete schema-2 capture + stable publication | `pluto` | `diaries-complete-backup-publish.timer` | 00:30 UTC daily |
| Verified publication pull | `mars` | `diaries-pull.timer` | 01:30 UTC daily |
| Timestamp snapshot creation/pruning | `mars` | existing 0035 timers | create hourly at :00, prune at :15 |
| Native incremental off-site replication | `mars` | `btrfs-native-push.timer` | 03:30 UTC daily |
| Receiver acceptance/receipt | `backup` | invoked by source push | no receiver scheduler |

The timing leaves an hourly snapshot boundary between the 01:30 collection and the 03:30 push. It is a default, not a hidden policy: external inventory may override calendars deliberately.

## Required production inventory intent

Inventory is external to this source bundle, so Step 11.4 does not silently edit it. The final intended state is equivalent to:

```yaml
# pluto
diaries_complete_backup_schedule_enabled: true

# mars
diaries_pull_install: true
diaries_snapshot_integration_enabled: true
diaries_pull_schedule_enabled: true
legacy_remote_rsync_push_enabled: false
btrfs_native_push_schedule_enabled: true

# already accepted on mars under 0035
btrfs_snapshot_activation_enabled: true
```

Retain existing host-specific path/identity settings. Do not copy this block over inventory wholesale.

## Cutover order

1. Deploy `local-backup.yaml` to `mars` with `legacy_remote_rsync_push_enabled: false`; confirm `/root/scripts/backup/backup.sh` no longer invokes `remote/backup.sh`. The local root backup still runs; only its historical off-site rsync phase is omitted.
2. Deploy `diaries.yaml` to `pluto` with `diaries_complete_backup_schedule_enabled: true`.
3. Confirm the existing `mars` snapshot creation/prune timers are still enabled and healthy.
4. Deploy `native-btrfs.yaml` to `mars` and `backup` with `btrfs_native_push_schedule_enabled: true` on `mars`. The role refuses native timer activation if the rendered legacy rsync phase is still active.
5. Exercise each new oneshot service deliberately once before relying on its timer, then leave timers enabled. Do not use a full/reseed native transfer for this test; the unattended push uses `--latest` and requires the accepted common parent.
6. Run `verification/0034-step11-4/verify-unattended.yaml` from `mango`. Preserve terminal output as runtime evidence.

## Native push behaviour

`btrfs-native-push --latest` obtains a validated source-snapshot list only through the constrained privileged endpoint. It selects the newest read-only `@data` snapshot, verifies the UUID again, and then either:

- returns success/no-op when that exact snapshot is already accepted;
- performs an incremental push from a receiver-accepted common parent; or
- fails closed if no accepted common parent exists.

It never turns `--latest` into an implicit full/reseed operation. Full baseline/reseed remains an explicit operator recovery action using `--snapshot` plus `--full`/`--reseed` as applicable.

## Monitoring and acceptance

The systemd journal and service result are the primary unattended audit trail. The live verifier requires enabled/active timers, successful previous service executions, fresh published/collected/snapshot/received media, a valid schema-2 manifest at `pluto` and `mars`, and absence of the old receiver pull helpers and active `mars` rsync off-site phase.

The verifier is read-only. Its `btrfs-native-push --latest --preflight` command validates the next native plan but does not protect, send or receive a snapshot.

Step 11.4 is not closed merely because source tests pass. Close it only after the explicit production inventory changes are deployed, the services have succeeded, the timers remain enabled, and the live verifier passes on `pluto`, `mars` and `backup`.

## Rollback

Disable `btrfs-native-push.timer`, `diaries-pull.timer` and `diaries-complete-backup-publish.timer` before changing transport ownership. Do not delete accepted received snapshots, receipts, the held `20261013-171228Z` checkpoint, the active protected parent, schema-2 generations, or Btrfs snapshot media as part of scheduling rollback.

If the historical rsync push must be reactivated for rollback, do so only after the native push timer is disabled and verify that exactly one off-site transport is active. The history-tool configuration limitation (`verification.required=false`) remains deferred to 0035-FEAT and is not changed by Step 11.4.
