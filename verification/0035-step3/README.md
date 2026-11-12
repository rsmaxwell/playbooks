# 0035 Step 3 — Receiver identity and retention contract

This step does **not** enable receiver-local snapshot timers or delete any data.

Current received repository: `/@data/mars-received/@data/<timestamp>`; acceptance receipts: `/@data/mars-received/.replication-state/<timestamp>.json`; transaction lock: `.replication-state/writer.lock`. These are separate from historical `/@data/backup` and from any locally managed `/@snapshots` namespace. The receive parent is an ordinary root-owned directory; received entries themselves are Btrfs subvolumes, not ordinary copy directories.

**Retention policy:** Received snapshots are not covered by the local root/@data GFS rules. No automated received-snapshot pruning is authorised. Preserve every accepted receive and its receipt until a separately reviewed receiver-pruning design proves source/receiver locks, a valid common incremental parent, and safe fail-closed handling for unreceipted or mismatched received entries. In particular preserve the most recent accepted receive and the last common send parent; protect any active send/receive pair. No deletion of the historical `/@data/backup` mirror or Snapper numeric snapshots is permitted.

Run from mango:

```bash
python3 verification/0035-step3/verify-source-contract.py
ansible-playbook verification/0035-step3/capture-backup.yaml --ask-vault-pass | tee /tmp/0035-step3-backup.txt
```

Check `UNRECEIPTED`, `MISSING_RECEIVED`, and every `RECEIPT ... matched=`. The capture is read-only; no claim of live success or Step 3 closure is made until its evidence is reviewed. Existing backup local snapshot manager configuration pointing to `diaries-mars-replica` is stale and is not used to authorise receiver retention or deletion.
