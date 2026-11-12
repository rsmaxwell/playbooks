# 0039-DEF: shared stale-qgroup maintenance for mars and backup

**Owner:** `roles/btrfs-replication/tasks/qgroup-maintenance.yaml`, invoked by
`btrfs-replication.yaml`; it uses the **single shared source**
`roles/snapshots/files/btrfs-clear-stale-qgroups.py`. The generic snapshots
role does not install it: that role intentionally refuses receiver hosts.

**Host-local configuration:** `/etc/btrfs-stale-qgroups.json` is a separately
rendered root-owned (`0600`) file on **each** host. Ansible selects endpoint
mode, filesystem, manager configuration path, expected writer lock and maximum
stale count from the effective host inventory; the common service passes only
`--config /etc/btrfs-stale-qgroups.json --execute`. The executable checks
this file against `/etc/btrfs-snapshot-manager.json` and refuses mismatches.
No distinct `mars` or `backup` Python implementation is maintained. Changing
the timer calendar uses the per-host Ansible setting, not the JSON file.

The script holds the canonical snapshot-manager lock **before** the endpoint
writer lock (matching the agreed-parent receiver lock order), requires the
writer lock to exist, verifies the manager's endpoint mode/lock contract and
Btrfs mount, and recognises native `<stale>` qgroups only. The filesystem is
`/media/usb` on mars and `/` on backup. `btrfs qgroup clear-stale` is the only
mutating action. A missing native command, unsupported qgroup-show output,
filesystem mismatch or more than 2000 stale qgroups **refuses** automatic
cleanup; there is no fallback to `qgroup destroy`, rescan or subvolume delete.
An `<under deletion>` entry is not treated as stale. This is periodic
housekeeping, not a cure for kernel qgroup-lifecycle bugs.

Both host gates default OFF:

```
btrfs_stale_qgroup_maintenance_install_enabled: false
btrfs_stale_qgroup_maintenance_enabled: false
```

After the Step 8 host baselines and Step 9 regression are reviewed, set
`...install_enabled: true` **on each host** in its effective Ansible inventory,
run the applicable `--check --diff` preview, deploy and inspect the dry-run
and installed service. For Step 10 guarded activation, set
`...maintenance_enabled: true` on each host and reapply the playbook.
The default schedule is 05:30 UTC on both hosts; active replication may
overrun and the nonblocking locks then report a visible deferral/failure.

Read-only manual inspection (each command on its named target over SSH):

```
# mars
sudo /usr/local/sbin/btrfs-clear-stale-qgroups --config /etc/btrfs-stale-qgroups.json
# backup
sudo /usr/local/sbin/btrfs-clear-stale-qgroups --config /etc/btrfs-stale-qgroups.json
```

Do not run `--execute` manually without the documented production activation
gate. The service's `--execute` is deliberate and is activated only via the
reviewed timer. The script leaves quota metadata alone when no stale entries
exist and reports `stale_before`, `stale_after`, and `removed` in the journal.
A failed/contended run returns nonzero and is not recorded as success.

Rollback: disable/stop `btrfs-clear-stale-qgroups.timer` on each host via the
Ansible activation variable, then review journal evidence. Never roll back
by blindly undoing legitimate quota metadata removals; preserve snapshots,
writer locks and source/receiver protection state.

## Deferred subvolume deletion (0039-DEF, 9 November 2026)

A Btrfs `qgroup show` entry marked `<stale>` can still correspond to an
asynchronously deleting subvolume (reported by `btrfs subvolume list -d`).
On `mars` the 9 November investigation found **11 pending subvolume IDs and
exactly the same 11 stale qgroups with non-zero accounting**. Native
`btrfs qgroup clear-stale` can remove other entries but return rc=1 with
`Device or resource busy` for these pending IDs. A quota rescan did not
clear that condition; an explicit `btrfs subvolume sync` also exceeded its
20-minute wait but deletion progressed in the background.

The shared executable now performs a read-only pending-deletion ID inventory
before and after the **single native clear-stale operation**. An exit code
from native clear-stale is accepted as an **expected deferral** only if:

- every diagnostic is exactly `ERROR: cannot delete qgroup 0/<ID>: Device or resource busy`,
  with the ID present in the observed deletion queue;
- every stale qgroup remaining after the operation is still in the
  post-operation deletion queue; and
- pre-existing non-stale qgroup entries remain unchanged.

It then logs `result=deferred_pending`, `deferred_pending=<count>`,
`stale_after=<count>`, `removed=<count>` and `native_rc=<exit code>`;
the service succeeds in the **maintenance/deferred** sense, **not** in the
"all stale qgroups absent" sense. The daily run can clear eligible entries
while the kernel completes outstanding deletions. A zero remaining count
logs `result=complete`. Any unexpected native error, unmatched stale ID,
unsupported pending-list format or changed non-stale inventory causes a
nonzero exit and must be investigated.

Do **not** interpret `systemctl` success alone as proof that stale qgroups
are zero. Read the journal's `result` and `deferred_pending` fields. Monitor
successive runs to ensure deferred queues eventually drain; a persistent
or growing queue is not accepted as feature closure. This service does not
start a rescan, wait for subvolume sync, delete subvolumes, or bypass locks.
