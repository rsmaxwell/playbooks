# 0035-FEAT Step 8 — Gate B acceptance workflow

Gate A passed on 2026-10-15 with `changed=0` on all hosts. This Gate B1 check **does not** invoke `verify` (which hashes the complete schema-2 backup), create snapshots, start replication, restore data, alter timers or delete files.

```sh
cd ~/playbooks
set -o pipefail
ansible-playbook verification/0035-step8/verify-history-lightweight.yaml --ask-vault-pass | tee /tmp/0035-step8-gate-b1.txt
```

Check that the restored path is an absolute, existing snapshot-resident dataset on `mars` and an immutable published generation on `pluto`. If actual published path differs, STOP and inspect configuration; do not alter source data to accommodate test assumptions.

## Controlled Gate B2 (not run here)

Reuse 0034 disposable off-site recovery Gates A–D closure, then separately demonstrate GFS boundary selection, concurrent pin/prune refusal, lost SSH/acknowledgement, interrupted full/incremental streams, duplicate receive, stale parent and disk-pressure failure in isolated Btrfs loopback filesystems. Capture exact source/received UUIDs, previous accepted receipt, read-only state and restore validity before/after each injection. Do not inject failures into the production push or destination.

The `verify` command and any full-dataset restore require a separately planned maintenance/disposable test. No run of this playbook proves complete data hashes or restore success.

## Gate B1 result and Gate B2 offline harness (2026-10-15)

Gate B1 live `show` and `path` passed on `mars` and `pluto`, both reporting manifest SHA-256 `c64f94a5211a16506838e74686ecd95acd56f56f8e98caff6e14c4a4a9ce4b65` for backup `20261015-003023Z`; no changes.

Run on `mango` after applying this patch:

```sh
cd ~/playbooks
python3 verification/0035-step8/verify-gate-b2-disposable.py
```

This test loads the real receiver/manager Python modules but uses temporary directories and mocks the privileged inspection endpoint. It tests failure decisions, not true interrupted SSH/Btrfs streams. It needs no sudo, Ansible Vault, Docker, mounted Btrfs, or network; it never calls the production receiver command-line entrypoint. **Gate B2 and Step 8 remain OPEN** pending isolated kernel/send/receive failure experiments and disposable restore validation.

## Gate B2 kernel integration harness (15 October 2026 — implementation, not executed)

`verify-gate-b2-btrfs-loopback.sh` is an **explicitly opt-in** root-only test. It creates three *new* 384 MiB loopback Btrfs filesystems under a private temporary directory, makes real read-only snapshots, tests successful full and incremental send/receive, and rejects truncated full/incremental streams and an incremental stream with a missing receiver parent. It checks earlier accepted data survives each failure. It does not access the production receiver, use network or SSH, issue receipts, operate on production paths, or change systemd units. Cleanup uses an EXIT trap and refuses to remove still-mounted images.

Run ONLY on an **isolated disposable Linux VM** with `btrfs-progs`, loop devices, sufficient free disk (~1.2 GiB), mount capabilities, and no production Btrfs mounts as part of this exercise:

```sh
cd ~/playbooks
bash -n verification/0035-step8/verify-gate-b2-btrfs-loopback.sh
sudo bash verification/0035-step8/verify-gate-b2-btrfs-loopback.sh --run-disposable \
  | tee /tmp/0035-step8-gate-b2-kernel.txt
```

Exit 77 is SKIP because kernel/tool prerequisites are missing. Do not mark kernel acceptance passed without actual PASS transcript. The test deliberately does **not** claim true SSH failure, real ENOSPC, receiver acceptance receipt publication, or end-to-end schema-2 recovery: those require separate isolated integration and evidence. Treat no-output, failure, or cleanup alert as a failure requiring review.

## Gate B2 kernel missing-parent correction (2026-10-15)

The first kernel run passed full receive, truncated-full rejection and incremental receive, then falsely failed its missing-parent assertion. Its `wrong-parent` directory was on the *same Btrfs filesystem* as a valid accepted parent in `received/`; Btrfs resolves parent identity across that filesystem, not only within the `btrfs receive` destination directory. This was an invalid negative test, **not evidence of a production receiver failure**. The revised harness uses a third, independent Btrfs loopback filesystem for the missing-parent negative test. Re-run the full harness and retain Step 8 OPEN pending actual results.
