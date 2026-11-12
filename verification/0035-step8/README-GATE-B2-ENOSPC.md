# 0035 Step 8 — disposable ENOSPC acceptance

This is a NEW, opt-in kernel-level ENOSPC harness. It creates two NEW 384 MiB loopback Btrfs filesystems and never contacts production hosts, SSH endpoints, or production receiver processes. Run **only in an isolated disposable Linux VM** with loop devices, Btrfs tools, root access, and at least 1 GiB free in its temporary directory.

```bash
cd ~/playbooks
bash -n verification/0035-step8/verify-gate-b2-enospc-loopback.sh
set -o pipefail
sudo bash verification/0035-step8/verify-gate-b2-enospc-loopback.sh --run-disposable | tee /tmp/0035-step8-gate-b2-enospc.txt
```

The harness confirms an accepted read-only baseline and source UUID; fills the *disposable receiver filesystem* with incompressible bytes until the kernel reports `No space left on device`; attempts a new full receive and requires failure; confirms the previously accepted baseline survives; removes the temporary pressure file; confirms recoverability afterward. Failure or skipped prerequisites must not be recorded as PASS. The harness does **not** exercise the fixed-path production receiver, its independent acceptance receipts, or SSH. It does not manipulate timers, replication pins or real data. It cleans up mounted filesystems and loop devices; if unmount fails it retains its workdir for manual investigation.

The previous 5 kernel send/receive tests passed on `mango` on 2026-10-15. The new ENOSPC test is **NOT RUN** until its log is captured. SSH disconnect and missing acknowledgement need a separate isolated transport test, and full schema-2 restore is supported only by the earlier 0034 closure summary until original transcripts are located.
