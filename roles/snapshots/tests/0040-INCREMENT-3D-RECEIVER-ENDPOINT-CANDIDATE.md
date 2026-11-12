# 0040-FEAT Increment 3D — Receiver observation endpoint candidate

Status: implemented and disposable-regression verified; **not deployed**.

This incremental ZIP installs only two new source-tree files plus this note. It does not modify Ansible tasks, sudoers, systemd schedules, snapshot retention, replication or state files.

The fixed-path candidate `roles/snapshots/files/btrfs-agreed-parent-endpoint.py` exposes an `--observe-receiver` *read-only* command. It requires root, checks the fixed receiver Btrfs filesystem UUID, calls existing Increment 3C observation while it holds receiver locks, and obtains per-snapshot Received UUID and readonly flags through fixed Btrfs commands. Existing Increment 3C receipt validation checks both filesystem identities and each receipt under locks. It refuses missing agreed-parent state, receipts, unsafe locks, pending deletion journal, invalid subvolume evidence and mismatches. The returned JSON explicitly denies transition and pruning authority.

## Safety gate

The source bundle does **not** install an agreed-parent state record on backup and the receiver role deliberately removes `/etc/sudoers.d/diaries-native-btrfs`. Do not expose this command through sudo or SSH yet. Prior to deployment, verify the effective receiver privilege boundary and root-owned fixed state provisioning, consistent state bootstrapping on both peers, and the snapshot manager lock path. Plan root-only endpoint installation, restricted invocations, and explicitly review `ansible-playbook btrfs-replication.yaml --check --diff --vault-password-file ~/.vault_pass.txt` output before applying anything. In particular, do not promote new states or release old pins while the legacy sender remains active.

## Disposable tests on mango

```
cd /home/richard/playbooks
for test in state protocol evidence ssh receiver endpoint; do
    python3 "roles/snapshots/tests/verify-0040-agreed-parent-${test}.py" || exit 1
done
python3 -m py_compile roles/snapshots/files/btrfs-agreed-parent-*.py roles/snapshots/tests/verify-0040-agreed-parent-*.py
```

Expected totals: 4 + 7 + 7 + 8 + 8 + 7 = 41 tests. This does not prove operation on the live backup filesystem.
