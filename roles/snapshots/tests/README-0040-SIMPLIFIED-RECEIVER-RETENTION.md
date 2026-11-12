# 0040 Step 12: simplified receiver retention source verification

Run on **mango, from `/home/richard/playbooks`**:

```bash
python3 roles/snapshots/tests/verify-0040-simplified-receiver-retention.py
python3 roles/snapshots/tests/verify-0040-agreed-parent-prune-guard.py
python3 roles/snapshots/tests/verify-0040-prune-source-selection.py
python3 roles/snapshots/tests/verify-0040-step05-adversarial.py
python3 roles/btrfs-replication/tests/verify-replication.py
```

These tests use isolated directories and mocked Btrfs output. They do not
prove live deletion safety or authorise enabling receiver pruning. The
receipt-independent path is distinct from the old receipt-based `receiver-plan`
and `receiver-prune` interfaces, which remain unavailable for deletion.

`receiver-simple-plan` verifies all Btrfs identities, holds, old-marker
absence and actual agreed-parent UUIDs under the manager lock. It does not
remove any snapshot or receipt. The receiver pruning timer stays disabled
until the approved live deletion gate; do not set its enable flag during
installation preview.

## Historical receipt lifecycle correction — 7 November 2026

The receipt file is immutable historical evidence, not a Btrfs identity source
or a permanent retention hold. The fixture suite verifies a received snapshot
with a receipt is eligible when its retention buckets/pins/holds permit it;
actual guarded pruning does not alter the receipt bytes, and a subsequent plan
accepts the resulting orphan receipt. Invalid symlinked receipt paths are
refused. The isolated real-Btrfs fixture in the Diaries feature tests exercises
this same behaviour using an actual received subvolume.
