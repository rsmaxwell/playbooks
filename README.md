# Ansible Playbooks

Ansible playbooks and roles for configuring the Ubuntu hosts, backup systems,
shared infrastructure and application deployments. The primary Playbooks
working copy is `/home/richard/playbooks` on the controller `mango`.

## Entry points

Run these from an SSH terminal on **mango**, in `/home/richard/playbooks`.
Ansible uses its configured default inventory under `/etc/ansible`.

| Playbook | Function |
| --- | --- |
| [`backup-collection.yaml`](backup-collection.yaml) | Configure the `mars` backup collection through the `backup-collection` role |
| [`snapshots.yaml`](snapshots.yaml) | Manage snapshot support through existing host-specific roles |
| [`btrfs-replication.yaml`](btrfs-replication.yaml) | Configure the native Btrfs sender and receiver endpoints on `mars` and `backup` |
| [`diaries.yaml`](diaries.yaml), [`ledger.yaml`](ledger.yaml) | Deploy the respective applications |
| [`bootstrap.yaml`](bootstrap.yaml), [`setup.yaml`](setup.yaml) | Bootstrap and system setup |

The `backup-collection` name is a **playbook, launcher and role**. Its role
contains the original `mars` backup installation tasks and includes
`roles/snapshots/`; native sender/receiver deployment remains in
`roles/btrfs-replication/`. The original `local-backup` and `remote-backup`
playbooks, launchers and the old `local-backup` role name have been retired.
`diaries-user-backup-cron.yaml` was a one-off repair entry point and is also
retired; the backup-collection role still manages the user cron schedule.
The inventory group names `local_backup` and `remote_backup`, established
configuration variable names, installed executables and systemd units are
unchanged. For the receiver snapshot context use
`snapshots.yaml --limit backup --tags snapshots`; for native replication use
`btrfs-replication.yaml --limit backup`.

For role details, see [`roles/backup-collection/README.md`](roles/backup-collection/README.md),
[`roles/snapshots/README.md`](roles/snapshots/README.md) and
[`roles/btrfs-replication/README.md`](roles/btrfs-replication/README.md).

## Running and checking deployments

For example, preview the two backup deployment entry points **without making
changes**:

```bash
cd /home/richard/playbooks
ansible-playbook backup-collection.yaml --limit mars --check \
  --vault-password-file ~/.vault_pass.txt
ansible-playbook btrfs-replication.yaml --limit 'mars,backup' --check \
  --vault-password-file ~/.vault_pass.txt
```

Only run the corresponding commands **without `--check`** when deliberately
applying configuration. Avoid `--diff` for normal production runs because
rendered configuration may contain sensitive material. Ansible roles can
manage timers, files and services; follow the relevant role's operational
instructions and check the target hosts before applying changes.

The effective inventory still matters: at the time of the 0045 refactor,
the operational inventory and secrets reside under `/etc/ansible` on `mango`,
not necessarily in this Git repository. Never commit plaintext secrets or
assume role defaults override group/host variables.

## Btrfs maintenance schedules

*Consolidated from the 0043-FEAT maintenance schedule document.*

The authoritative schedule is the operational inventory file
`/etc/ansible/group_vars/all/btrfs-maintenance-schedule.yaml` on `mango`.
There is no required second schedule file in the Playbooks Git repository.
Ansible discovers YAML files in `group_vars/all` automatically; no special
installer or registration is required. The filename is
`btrfs-maintenance-schedule.yaml` throughout.

| UTC | Host | Service |
| --- | --- | --- |
| 01:30 daily | mars | Diaries production pull |
| Hourly at :00 | mars | Snapshot creation |
| 03:30 daily | mars | Simplified replication sender |
| **04:15 daily** | mars | Source snapshot prune (up to 32 sets) |
| **04:15 daily** | backup | Receiver snapshot prune (up to 10 sets) |
| 05:30 daily | both | Guarded stale-qgroup cleanup |

The source-prune service limit rises from 10 to 32 snapshot sets per run so
it can service daily retention after approximately 24 hourly snapshot
creations. This does not change the retention policy, delete the agreed
parent, release checkpoint holds, or alter timer activation flags.
`btrfs-snapshot-prune.timer` retains `Persistent=true`, so on deployment a
missed daily event **may trigger a catch-up run** rather than waiting until
04:15 tomorrow; check journal and snapshot status. Receiver pruning retains
`Persistent=false`. Snapshot deletion queues asynchronous Btrfs cleanup:
free-space reclamation and stale-qgroup reconciliation can continue after
systemd reports the prune command finished.

### Make schedule changes

In the **mango SSH terminal** as `richard`, edit the authoritative inventory
file `/etc/ansible/group_vars/all/btrfs-maintenance-schedule.yaml` using your
normal privileged editor or WinSCP workflow, then check the effective values:

```bash
cd /home/richard/playbooks
ansible-inventory --host mars --yaml --vault-password-file ~/.vault_pass.txt
ansible-inventory --host backup --yaml --vault-password-file ~/.vault_pass.txt
```

**Effective inventory** must always be checked: more specific host/group
variables may override values from `group_vars/all`. The 0043 work removed
the obsolete `mars` host override for source-prune scheduling.

Preview, inspect, and apply the normal roles (never modify timers manually):

```bash
cd /home/richard/playbooks
ansible-playbook snapshots.yaml --limit mars --tags snapshots \
  --check --vault-password-file ~/.vault_pass.txt
ansible-playbook btrfs-replication.yaml --limit 'mars,backup' \
  --skip-tags qgroup-maintenance --check \
  --vault-password-file ~/.vault_pass.txt

ansible-playbook snapshots.yaml --limit mars --tags snapshots \
  --vault-password-file ~/.vault_pass.txt
ansible-playbook btrfs-replication.yaml --limit 'mars,backup' \
  --skip-tags qgroup-maintenance --vault-password-file ~/.vault_pass.txt
```

Use `--skip-tags qgroup-maintenance` only to avoid altering the accepted
0039 activation during 0043. The 05:30 timer calendar remains unchanged.
No extra source/receiver coordination is needed: pruning runs on separate
filesystems with independent locks, and replication-parent protection still
applies on both ends. Monitor the first 04:15 daily run and follow-on
05:30 stale-qgroup cleanup.

### Rollback

Restore the previous calendar values in the authoritative
`/etc/ansible/group_vars/all/btrfs-maintenance-schedule.yaml`, then re-run
the regular Ansible playbooks. Leave checkpoint holds, replication parent
state and retention settings unchanged. Do not just remove the installed
schedule file without checking what lower-precedence defaults and host/group
overrides would take effect.

The obsolete single-purpose `scripts/maintenance-schedule.py` and its
`verify-maintenance-schedule.py` test are retired by 0043. The standard
Ansible inventory and existing Ansible roles are all that is required for
managing these schedules. The inventory is outside Playbooks Git; preserve
its configuration through existing host backups and 0043 evidence receipts.
