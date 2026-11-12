# 0034-FEAT Step 10 — integrate with 0035 on `mars`, then `backup`

Step 10 is intentionally **two-stage and non-activating by default**. First prove the verified receive → snapshot → history contract manually on `mars`. Only after that succeeds should `backup` be changed. Native timers and Snapper handover stay disabled during this acceptance unless a later explicit 0035 migration decision authorises them.

## 0. Source regression on `mango`

Run from `~/playbooks`:

```bash
python3 roles/snapshots/tests/verify-btrfs-snapshot-manager.py
python3 roles/snapshots/tests/verify-diaries-backup-history.py
python3 roles/local-backup/tests/verify-diaries-pull.py
python3 roles/remote-backup/tests/verify-whole-backup-pull.py

python3 -m py_compile \
  roles/snapshots/files/btrfs-snapshot-manager.py \
  roles/snapshots/files/diaries-backup-history.py \
  roles/snapshots/files/btrfs-extent-sharing.py \
  roles/local-backup/files/backup-machine/diaries-pull.py \
  roles/remote-backup/files/whole-backup-pull.py
```

Then rerun the established 0034 regression set from Step 9. Step 10 changes the receiver/snapshot integration but must not regress schema-2 publication, restore compatibility, isolation or deployment semantics.

## 1. Capture `mars` baseline before deployment

```bash
ansible-playbook verification/0034-step10/capture-baseline.yaml \
  -e step10_host=mars --ask-vault-pass
```

Record Btrfs mounts/subvolumes, existing Snapper configurations, timer states and root cron. In particular, prove the current 02:00/02:15 jobs and whether any other writers target `/media/usb/@data/backup`.

**Gate:** do not enable native timers while an uncoordinated writer remains.

## 2. Deploy `mars` integration source only

```bash
ansible-playbook local-backup.yaml --limit mars \
  -e '{"diaries_pull_install":true,"diaries_snapshot_integration_enabled":true}' \
  --ask-vault-pass
```

Because both snapshot activation flags default to false, this deployment may install/preflight the native manager, history tool, extent tool, unit files and verified receive helper, but it must not enable the native timers and must not stop/disable Snapper timers.

On `mars`:

```bash
~/scripts/backup/diaries-pull.sh --preflight
sudo btrfs-snapshot-manager status
systemctl is-enabled btrfs-snapshot-create.timer 2>/dev/null || true
systemctl is-enabled btrfs-snapshot-prune.timer 2>/dev/null || true
```

Compare scheduler state with the baseline. The preflight must create no transfer staging or eligibility marker.

## 3. First verified `pluto` → `mars` receive and first snapshot

On `mars`:

```bash
~/scripts/backup/diaries-pull.sh
sudo btrfs-snapshot-manager status
sudo btrfs-snapshot-manager create
sudo btrfs-snapshot-manager list
sudo diaries-backup-history list
sudo diaries-backup-history list --all
```

Record:

```text
MARS_ID_A=<Diaries backupId>
MARS_SNAPSHOT_A=<native snapshot timestamp>
```

Acceptance requires the pull JSON to report `snapshotEligible: true`, manager status to report the same logical dataset/ID, and history to show one verified summary row.

## 4. Repeat the same Diaries ID in a second whole-backup snapshot

Do **not** run another Diaries pull. Create a second snapshot after the first command has completed:

```bash
sleep 2
sudo btrfs-snapshot-manager create
sudo diaries-backup-history list
sudo diaries-backup-history list --all
```

Record `MARS_SNAPSHOT_B`. The summary `list` must still show **one** row for `MARS_ID_A`, now with `SNAPSHOTS=2`; `list --all` must show both timestamp occurrences.

### Prove Btrfs extent sharing

Resolve the same backup occurrence in both snapshots:

```bash
A=$(sudo diaries-backup-history path "$MARS_ID_A" --snapshot "$MARS_SNAPSHOT_A")
B=$(sudo diaries-backup-history path "$MARS_ID_A" --snapshot "$MARS_SNAPSHOT_B")
REL=$(sudo find "$A/files" -type f -size +1M -printf '%P\n' | head -1)
echo "$REL"
sudo btrfs-extent-sharing "$A/files/$REL" "$B/files/$REL"
```

The tool first proves equal size and SHA-256 and then compares FIEMAP physical ranges from `filefrag`; at least one shared physical extent is required. This is the Step 10 proof of snapshot extent sharing, rather than relying on apparent `du` sizes.

## 5. Publish a later Diaries ID on `pluto`, receive it on `mars`, snapshot it

On `pluto`:

```bash
cd ~/projects/diaries
./scripts/backup-dataset.sh publish-preflight
./scripts/backup-dataset.sh publish
./scripts/complete-dataset-publisher.py \
  --published-root "$PWD/data/diaries-backup" show-current-id
```

Record the new ID as `MARS_ID_B`; it must differ from `MARS_ID_A`.

Back on `mars`:

```bash
~/scripts/backup/diaries-pull.sh
sudo btrfs-snapshot-manager status
sleep 2
sudo btrfs-snapshot-manager create
sudo diaries-backup-history list
sudo diaries-backup-history list --all
sudo diaries-backup-history verify "$MARS_ID_A"
sudo diaries-backup-history verify "$MARS_ID_B"
```

Acceptance requires two summary rows: the earlier ID retained across at least two snapshots and the later ID in the new snapshot. Both full schema-2 history verifications must pass.

**Do not delete the earlier snapshots or legacy Snapper media.**

## 6. Capture `backup` baseline before changing it

Only after the `mars` gate passes:

```bash
ansible-playbook verification/0034-step10/capture-baseline.yaml \
  -e step10_host=backup --ask-vault-pass
```

Also confirm from `backup` which SSH alias/credentials can read the `mars` native snapshot tree. The role defaults to `backup_pull_host=mars`; override it at deployment if the real restricted alias differs.

Do not alter the historical `mars` 02:15 push yet.

## 7. Deploy `backup` integration source only

For an SSH alias of `mars`:

```bash
ansible-playbook remote-backup.yaml \
  -e '{"backup_pull_install":true,"remote_snapshot_integration_enabled":true,"backup_pull_host":"mars"}' \
  --ask-vault-pass
```

Substitute the proven restricted alias if it is not `mars`. Again, native timers and Snapper handover remain default-off.

On `backup`, select one **verified read-only `mars` snapshot** containing `MARS_ID_B`; use `MARS_SNAPSHOT_C` below for that timestamp:

```bash
sudo whole-backup-pull --snapshot "$MARS_SNAPSHOT_C" --preflight
```

This preflight is non-mutating.

## 8. Controlled `mars` snapshot → `backup` pull and local snapshot

First ensure the historical `mars` push is not currently running. For the controlled test it may remain configured, but there must be no overlapping writer during this manual acceptance.

On `backup`:

```bash
sudo whole-backup-pull --snapshot "$MARS_SNAPSHOT_C"
sudo btrfs-snapshot-manager status
sudo btrfs-snapshot-manager create
sudo diaries-backup-history list
sudo diaries-backup-history list --all
sudo diaries-backup-history verify "$MARS_ID_B"
```

Record:

```text
BACKUP_SNAPSHOT_A=<backup native snapshot timestamp>
```

The pull reads from the immutable `mars` snapshot, not the live `mars` mirror. The backup-host marker is invalidated before the writable mirror changes and is recreated only after independent schema-2 validation. On a failed transfer, **do not** run snapshot creation; the manager should reject a missing/stale marker anyway.

## 9. Repeat unchanged data on `backup`

Without another pull:

```bash
sleep 2
sudo btrfs-snapshot-manager create
sudo diaries-backup-history list
sudo diaries-backup-history list --all
```

The same `MARS_ID_B` must remain one summary row with an increased snapshot occurrence count. Use `btrfs-extent-sharing` between the two `backup` occurrences exactly as on `mars` to prove local extent sharing. Do not infer sharing from rsync between hosts; each host establishes sharing only between its own Btrfs snapshots.

## 10. Scheduling / Snapper handover remains a separate explicit gate

The source now supports activation, but Step 10 acceptance should not set either of these merely to prove integration:

```yaml
btrfs_snapshot_activation_enabled: true
btrfs_snapshot_snapper_handover_enabled: true
```

Before unattended activation, complete the 0035 writer inventory. Known `mars` local user/root backup wrappers and the Diaries pull now use the shared writer lock; any additional intermittent-device writers must be reconciled too. On `backup`, first replace/disable the historical live `mars` push so the new backup-initiated pull is the only writer path.

## Step 10 close-out evidence required

Do not mark Step 10 closed until evidence contains:

- focused and full source regressions on `mango`;
- pre/post deployment scheduler baselines proving source deployment did not activate timers or hand over Snapper;
- `mars` verified pull, two snapshots containing the same ID, a later ID, deduplicated history and full history verification;
- Btrfs physical-extent sharing proof on `mars`;
- `backup` pull from an explicit immutable `mars` snapshot, independent schema-2 validation, local snapshot/history acceptance and local extent-sharing proof;
- confirmation that no unverified/mixed snapshot is advertised as restorable; and
- rollback notes preserving all prior read-only snapshots and legacy Snapper media.
