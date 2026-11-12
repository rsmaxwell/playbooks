# 0035 Step 2 — Preserve the existing mars snapshot manager

This is a read-only evidence gate. It does **not** deploy, create, prune, delete, send, or receive snapshots. The existing mars hourly create and quarter-past prune timers remain unchanged.

From mango:

```bash
cd ~/playbooks
python3 roles/snapshots/tests/verify-btrfs-snapshot-manager.py
python3 verification/0035-step2/verify-source-contract.py
ansible-playbook verification/0035-step2/capture-mars.yaml --ask-vault-pass | tee /tmp/0035-step2-mars.txt
```

Review the captured source UUID, nested subvolumes, protected/held snapshot read-only flags and UUIDs, timer state and writer/transfer lock coordination. A `PASS` in the static check does not prove on-host lock behaviour or off-site lineage; those require live evidence. Do not close Step 2 until the capture has been reviewed. Protect the accepted incremental parent and the 0034/0035 checkpoint. Never bulk-delete numeric Snapper snapshots.
