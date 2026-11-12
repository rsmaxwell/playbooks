# 0035 Step 6 — joint 0034 native replication safety verification

Run from `mango` after applying this verification-only patch:

```bash
cd ~/playbooks
python3 verification/0035-step6/verify-source-contract.py
python3 roles/remote-backup/tests/verify-native-btrfs-push.py
python3 roles/remote-backup/tests/verify-replication-protection.py
ansible-playbook verification/0035-step6/capture-joint.yaml --ask-vault-pass | tee /tmp/0035-step6-joint.txt
```

Read the output for `MATCH=False`, missing receipts, absent protection, changed timers, or UUID mismatch. The capture is **read only**. Do not execute `--full`, `--reseed`, prune `--apply`, or interrupted transfers for this gate. Existing 0034 full/incremental and disposable recovery evidence should be cross-referenced, not recreated on production solely for acceptance. No new schedules or privileges are installed. The legacy rsync verification marker is not a native acceptance receipt.

Step 6 remains open until the evidence review confirms the common source/receiver identity, baseline and incremental receipts, transfer-size and allocation evidence, and the applicability of existing interruption/race tests. Do not confuse the static checks with a live interruption rehearsal.
