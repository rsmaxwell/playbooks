# 0035 Step 8 Gate B2 — isolated SSH disconnect and receipt ENOSPC

These **opt-in destructive-to-test-volume only** scripts do not contact or edit `mars`, `backup` or `pluto`. Run on a disposable Linux VM with loop devices/Btrfs and OpenSSH server installed. The tests are **not** proof of a full production sender-to-receiver integration or successful schema-2 restoration.

```bash
cd ~/playbooks
bash -n verification/0035-step8/verify-gate-b2-ssh-disconnect.sh
bash -n verification/0035-step8/verify-gate-b2-receipt-enospc.sh
set -o pipefail
sudo bash verification/0035-step8/verify-gate-b2-ssh-disconnect.sh --run-disposable | tee /tmp/0035-step8-ssh-disconnect.txt
sudo bash verification/0035-step8/verify-gate-b2-receipt-enospc.sh --run-disposable | tee /tmp/0035-step8-receipt-enospc.txt
```

## Scope and safeguards

- SSH test launches a temporary `sshd` listening **only on 127.0.0.1** with temporary host/client keys, authenticates a local non-root account, kills the SSH client before `ACCEPTED` could be emitted, and ensures no acknowledgement was produced. Run via `sudo` from a non-root local account. Requires `openssh-server`. It does not exercise the production sender's pin lifecycle; earlier sender fault-injection tests cover pin preservation.
- Receipt test allocates a new 384 MiB Btrfs loopback filesystem, imports the **actual `atomic_receipt` function** from `roles/remote-backup/files/btrfs-native-push-receiver.py`, redirects only its `STATE` global to temporary storage, atomically writes a baseline receipt, fills the test filesystem to genuine `ENOSPC`, attempts a new receipt and verifies old accepted state remains and new acceptance is absent. It does not invoke the receiver CLI or change its installed configuration.
- Both scripts require explicit `--run-disposable`, decline without prerequisites (exit 77), and clean up created resources. If loopback unmount cannot complete, the test directory is retained for inspection. They make **no assertions** about disk usage/transfer bytes in real production.
- Do not run on production hosts. Never delete legacy snapshots or enable receiver snapshot timers as part of acceptance.

## Status

Scripts pass Bash syntax validation in source. Real execution and acceptance transcripts are **PENDING**. The Step 8 evidence matrix must not record either scenario as PASS until operator logs are reviewed.
