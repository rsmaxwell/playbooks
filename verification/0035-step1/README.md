# 0035-FEAT Step 1 — reconcile observed host state and baseline

This verification is deliberately **read-only**. It reconciles the state left by the completed 0034 production rollout with the current 0035 design before any further snapshot-manager migration or retention work is authorised.

It does not deploy code, create/prune snapshots, start/stop timers, run a backup, start a Btrfs send/receive, alter cron, or modify the retained historical rsync mirror.

## 1. Source safety regression on `mango`

From `~/playbooks`:

```bash
python3 verification/0035-step1/verify-source-contract.py
```

Expected:

```text
PASS: 0035 Step 1 baseline capture is three-host and read-only by source contract
```

## 2. Capture the live baseline

Run the capture once across all three production hosts:

```bash
ansible-playbook verification/0035-step1/capture-baseline.yaml --ask-vault-pass
```

For an evidence file that can be returned for review:

```bash
mkdir -p /tmp/0035-step1
ansible-playbook verification/0035-step1/capture-baseline.yaml --ask-vault-pass \
  | tee /tmp/0035-step1/baseline.txt
```

The playbook reports only non-secret operational state: filesystem and subvolume identities, installed helper hashes, manager configuration, snapshot/receipt identifiers, Snapper inventory, unit definitions/states, cron entries and matching running transfer processes. It does **not** read `.env`, SSH private keys, vault files or database credentials.

## 3. Reconciliation checklist

Step 1 can be closed only after the captured output establishes all of the following:

- `pluto`: actual filesystem type for the live Diaries publication path and whether any relevant Btrfs mount exists. If it remains ext4, record that native Btrfs snapshots are unavailable there.
- `mars`: filesystem UUID/mount for `/media/usb`; subvolume identity for `@data`; the managed `@snapshots` root; timestamp snapshot IDs/UUIDs and read-only inventory; current manager configuration; checkpoint holds and replication protections.
- `backup`: filesystem UUID/mount; `@data` identity; the retained historical `/@data/backup` path; native received snapshots under `/@data/mars-received/@data`; accepted receiver receipts and source/received UUID lineage.
- both Btrfs hosts: remaining Snapper configurations/numeric snapshots and actual Snapper timer state. Legacy snapshots are inventory only and must not be deleted by Step 1.
- scheduler truth rather than source defaults: user/root cron plus `diaries-pull`, native snapshot create/prune, native off-site push and relevant Snapper timers.
- current transfer truth: whether rsync, `btrfs send`/`receive`, `diaries-pull`, native push or legacy backup wrappers were active during capture.
- the old `/@data/backup` receiver is explicitly classified as historical/non-native and remains untouched.

## 4. Expected carry-forward facts from 0034 — verify, do not assume

The 0034 close-out recorded a working unattended chain with a production schema-2 publication on `pluto`, a verified timestamp snapshot on `mars`, and an accepted incremental native receive on `backup`. It also recorded the `mars` user backup cron move to **01:45 UTC**, historical rsync off-site scheduling disabled, source-initiated native push accepted, and checkpoint `20261013-171228Z` retained.

Those are comparison points only. Step 1 exists specifically to reconcile them with the **current live host state**. A mismatch should be recorded and explained rather than automatically "fixed" by this playbook.

## 5. Closure evidence

Preserve the `baseline.txt` output with the 0035 Step 1 change-control evidence. Review it for host/path/UUID/scheduler consistency, then update the feature evidence with a concise accepted baseline. Do not mark Step 1 closed merely because the capture playbook ran successfully; closure requires reconciliation of the results.

## Snapper timeout and quota-rescan evidence (15 October 2026)

Both Btrfs hosts now capture `btrfs quota rescan -s` independently (15-second
query timeout). Snapper configuration discovery has a 20-second timeout and each
per-configuration `snapper list` has a 30-second timeout, with an additional
five-second termination grace period. A timeout/nonzero exit is reported as
`INCOMPLETE` with its exit code; remaining checks continue. In particular, an
incomplete legacy Snapper inventory is **not** evidence that snapshots are absent.
The `backup` host has observed an active Btrfs quota-group rescan and a blocked
`snapper -c @data list`; this remains an open reconciliation finding until
reviewed. The playbook does not change or stop the rescan.
