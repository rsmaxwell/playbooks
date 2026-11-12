# 0040-FEAT Step 12 — Simplified receiver retention

## Active deployment (7 November 2026)

The **shared** `roles/snapshots/files/btrfs-snapshot-manager.py` implements
source retention and receiver retention against the same occupied-bucket
policy (48 hourly, 14 daily, 12 weekly, 24 monthly, 5 yearly; minimum age
30 minutes). The receiver has two commands:

- `receiver-simple-plan` — read-only inventory and candidate classification.
- `receiver-simple-prune --max-delete N` — explicitly gated deletion with a
  bounded durable transaction journal and revalidation.

Receiver pruning was explicitly authorised and **activated on `backup` on
7 November 2026**, daily at **04:15 UTC**, maximum **10** deletions per run.
Activation checks confirmed the manager checksum, enabled configuration,
active/enabled timer and correct `ExecStart`. At activation, the live plan
retained 30 snapshots, preserved 27 historical receipts and reported zero
candidates. The **first unattended execution has not yet been accepted**;
it is scheduled for 8 November 2026 at 04:15 UTC.

Role defaults remain safety-first (`btrfs_simplified_receiver_retention_install_enabled:
false`, `btrfs_simplified_receiver_prune_enabled: false`). Production enables
both gates **only on `backup`** through Ansible inventory. The receiver's
systemd service invokes `receiver-simple-prune --max-delete 10`, but the
manager's own fail-closed safety checks impose additional restrictions.
Keep the separate source replication timer at 03:30 UTC unchanged.

## Identity verification and protection

- Every retained receiver snapshot is checked using actual Btrfs `Received
  UUID`, subvolume identity and read-only state. Receipt contents do not prove
  its identity.
- Agreed current and previous parent snapshots, newer unacknowledged receives,
  historical/legacy agreed-parent pins and explicit checkpoint holds remain
  protected independently of the retention buckets.
- Historical legacy receipts are kept unchanged as forensic records. They no
  longer permanently protect the associated snapshot from normal policy
  expiry. After an authorised deletion, an orphaned regular receipt can be
  expected and is reported without removing its evidence bytes.
- Symlink or non-file receipt entries, inconsistent snapshot identities,
  unsafe checkpoint metadata or a pending prune journal fail closed.
- The manager shares the receiver's lock. Before deleting each candidate it
  revalidates that candidate and its protected dependencies. A journal is
  persisted before Btrfs deletion; a questionable interruption prevents
  subsequent unattended deletions pending operator review.

The plan reports `historical_receipts_preserved`,
`historical_receipts_on_candidates` and `historical_receipts_orphaned`.
The bucket algorithm counts *occupied* hours/days etc., **not an elapsed
48-hour cutoff**. Having 30 snapshots may therefore yield no deletion
candidates even when the oldest is several weeks old.

## Verification and emergency controls

From `mango`, inspect the effective receiver variables via
`ansible-inventory --host backup --vault-password-file ~/.vault_pass.txt`.
On `backup`, the timer and service are
`btrfs-receiver-simple-prune.timer` and
`btrfs-receiver-simple-prune.service`; the manager configuration is
`/etc/btrfs-snapshot-manager.json`.

Read-only checks (from an SSH terminal on `mango`):

```bash
ssh backup 'sudo -n systemctl list-timers --all btrfs-receiver-simple-prune.timer'
ssh backup 'sudo -n systemctl show btrfs-receiver-simple-prune.timer -p ActiveState -p UnitFileState'
ssh backup 'sudo -n /usr/local/sbin/btrfs-snapshot-manager --config /etc/btrfs-snapshot-manager.json receiver-simple-plan'
```

To inspect a specific unattended run, read `journalctl` and service
`ExecMainStatus`, and independently verify equal agreed-parent state on
`mars` and `backup`. A successful zero-deletion run is valid if the plan
has no eligible candidates; disposable real-Btrfs deletion and receipt
preservation have already been accepted.

**Do not manually invoke `receiver-simple-prune` on production** merely to
produce deletion evidence, nor change the timer or maximum deletion count
without authorisation. Never remove a pending prune transaction journal to
force another run; first classify and reconcile the interrupted transaction.
Historical acceptance reports and terminal evidence remain under the Diaries
`0040-FEAT` feature directory, not in the operational Playbooks repository.
