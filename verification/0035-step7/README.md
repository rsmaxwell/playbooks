# 0035-FEAT Step 7 — staged deployment gate

Status: IMPLEMENTED — live verification pending. **Read only.**

Apply this package to `~/playbooks` on mango. No changes are made to mars, pluto or backup by this playbook.

```bash
cd ~/playbooks
python3 verification/0035-step7/verify-source-contract.py
ansible-playbook verification/0035-step7/verify-staged.yaml --ask-vault-pass | tee /tmp/0035-step7-staged.txt
ansible-playbook verification/0035-step6/capture-joint.yaml --ask-vault-pass | tee /tmp/0035-step7-joint.txt
```

**Stop on any mismatch.** Reconcile source and installation paths before authorising targeted installation. A previously installed file can legitimately be from an earlier revision; do not interpret a mismatch as data corruption. If drift is found, review with `--check --diff` against the relevant scoped installation playbook from Steps 4 or 5, rather than applying the broad snapshots/remote-backup roles indiscriminately. No native receiver snapshots or timers are created here. Existing 0034 receipts prove previous initial and incremental acceptance, not a new transfer in this Step.

Gate also requires review of `0035` Step 2/3/6 transcript lineage, historical `/@data/backup`, checkpoint and replication protection. Verify installation scripts and host scheduler states without deleting, pruning, snapshotting, receiving, or changing systemd units. If all checks pass, record evidence in Diaries Step 7 and mark closed only after review.
