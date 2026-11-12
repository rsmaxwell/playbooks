# 0035-FEAT Step 9 — controlled scheduler migration

## Gate 9A — mandatory observation, no mutations

From `mango`, with Playbooks checked out at the intended revision:

```bash
cd ~/playbooks
set -o pipefail
ansible-playbook verification/0035-step9/preflight.yaml --ask-vault-pass | tee /tmp/0035-step9-preflight.txt
```

Capture `git rev-parse HEAD` in both repositories and attach `/tmp/0035-step9-preflight.txt` to Step 9 evidence. The playbook is read-only; it refuses active receiver scheduling and legacy rsync conflict. Ansible recap must show **changed=0**, failed=0, all three hosts reached. Review source protection pins, dry-run and timers before authorization.

## Gate 9B — deliberate cutover (NOT AUTHORIZED by this package)

Existing role controls (do not change them blindly):

- `btrfs_snapshot_activation_enabled`: enables creation **and pruning** timers together. Do not set until pruning is explicitly approved on mars; there is no creation-only switch in this role.
- `btrfs_snapshot_snapper_handover_enabled`: stops Snapper timeline/boot only after native activation and verified-Diaries barrier. Preserve `snapper-cleanup.timer` for numeric legacy snapshots.
- `btrfs_native_push_schedule_enabled`: source-only push timer; existing Ansible role refuses enabling alongside legacy remote rsync phase.
- `btrfs_snapshot_retire_legacy_snapper_timers`: separate retirement switch. Do not set without a documented operator decision. Never delete historical Snapper snapshots.

Do not edit timers, trigger native transfer, execute `prune --apply`, or run `snapper-retirement.yaml` as part of Gate 9A. Keep all `backup` native snapshot timers disabled. Before any 9B rollout, explicitly approve source creation+pruning policy and compare old/new timer overlap; capture before/after state and one unattended cycle.

## Gate 9C — rollback and operational evidence

If an approved migration later fails, **stop native create/prune or push timers first** (timer-only, not received snapshots), preserve snapshot pins, receipts, accepted parents and existing legacy datasets, then restore the previous approved scheduling state from recorded preflight evidence. Do not reactivate rsync while native push is active, never reseed implicitly, and never delete source or receiver state during rollback. Re-run Step 8 read-only acceptance before resuming automated changes.

Step 9 and overall feature remain OPEN until 9A evidence, controlled 9B approval/observation, 9C rollback review and source revision reconciliation are recorded.

## Gate 9C — read-only final live verification

After formally adopting the Gate 9A observed state at Gate 9B (no timer changes), run:

```bash
set -o pipefail
ansible-playbook verification/0035-step9/verify-gate-9c.yaml --ask-vault-pass | tee /tmp/0035-step9-gate9c.txt
```

Requires `mars`, `backup`, `pluto`; all tasks must be `changed=0, failed=0`. It verifies creation, prune and push timer states, disabled Snapper timers, zero incomplete timestamp sets, snapshot verification marker, checkpoint and replication-protection inventories, last push success, passive receiver, and ext4 schema-2 publication. It does **not** run prune `--apply`, start timers, or alter production. A passing check is a point-in-time state, not a claim that future pruning is error-free.

### Rollback (manual, not automatically run)

If activation or subsequent operation is unsafe, freeze new destructive or transferring activity before troubleshooting. Capture `systemctl status` and `journalctl` first. On `mars`, an operator may use `sudo systemctl disable --now btrfs-snapshot-prune.timer btrfs-native-push.timer` after checking for an active push; disabling timers does **not** interrupt an already-running service. Avoid stopping active Btrfs transfers. Leave `btrfs-snapshot-create.timer` running unless snapshot creation itself is unsafe. Preserve checkpoint holds, candidate/parent pins and receiver receipts; never delete them as a rollback shortcut. On `backup`, keep native snapshot timers disabled. Never automatically re-enable Snapper, legacy rsync, a receiver-side timer or reseed. Restoration of service requires diagnosis and an explicitly approved change, then a fresh Gate 9A/9C check.
