# 0035 Step 8 — Gate B2 transport/receipt fault injection

Run on `mango` after applying the ZIP (no root, Vault, SSH or Btrfs mounts):

```bash
cd ~/playbooks
python3 verification/0035-step8/verify-gate-b2-transport-faults.py | tee /tmp/0035-step8-gate-b2-transport.txt
```

This harness imports the existing production sender and receiver Python modules and injects simulated SSH status 255, sender status 141, a missing post-send acceptance receipt, an accepted receipt, and `ENOSPC` during atomic receipt publication. It asserts protection-pin lifecycle, previously accepted receipt retention, and absence of a new receipt. It does **not** create an SSH connection, exercise real storage exhaustion at receipt publication, or change actual host state. Real-network disconnect remains for a separately authorised isolated endpoint integration test.
