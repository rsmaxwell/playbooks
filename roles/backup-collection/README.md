# backup-collection role — mars backup and verified Diaries integration

The existing `mars` local backup jobs remain in place. Step 10 adds an opt-in verified Diaries receive and a shared whole-backup writer lock so known local writers can be coordinated with 0035 snapshot creation.

`diaries_pull_install` defaults to `false`. When explicitly enabled, the role installs `diaries-pull.py`, `complete-dataset-publisher.py`, `complete-dataset-manifest.py` and `diaries-pull.sh` under the normal user's `~/scripts/backup`. It creates no cron entry. Step 11.4 also installs a systemd service/timer for the pull; the timer remains disabled unless `diaries_pull_schedule_enabled: true` is explicitly supplied.

For the Step 10 deployment use the receiver together with `diaries_snapshot_integration_enabled: true`. The configured defaults are:

```yaml
diaries_pull_destination_parent: /media/usb/@data/backup/pluto
diaries_pull_snapshot_source_root: /media/usb/@data
diaries_pull_verification_marker: /media/usb/@data/backup/.diaries-snapshot-verified.json
diaries_pull_repository_lock: /media/usb/@data/backup/.btrfs-snapshot-writer.lock
diaries_snapshot_diaries_relative_path: backup/pluto/diaries-backup
diaries_snapshot_marker_relative_path: backup/.diaries-snapshot-verified.json
```

The pull holds the repository writer lock exclusively, rsyncs the stable `pluto` publication into a private incoming tree while the remote publisher shared lock is held, independently verifies schema-2, atomically publishes the receiving generation, verifies current again, and only then atomically writes `snapshotEligible=true` metadata. A failed pull never advances the stable receiving generation and never writes a new eligibility marker.

The normal-user and root machine backup wrappers also take the same whole-backup lock. This serialises the known `mars` writers with one another and with native snapshot creation. Before enabling automatic native snapshots, inventory any other device/client writers to `/media/usb/@data/backup`; an uncoordinated external writer remains a blocker to unattended activation.

Run the non-mutating check first:

```bash
~/scripts/backup/diaries-pull.sh --preflight
```

Run a deliberate receive only after preflight:

```bash
~/scripts/backup/diaries-pull.sh
```

A successful receive emits JSON containing the `backupId`, `logicalDataset`, marker path and `snapshotEligible: true`.

The historical 02:15 root backup job may retain `remote/backup.sh` as a rollback transport, but Step 11.4 introduces `legacy_remote_rsync_push_enabled`. Keep it `true` before cutover to preserve current behaviour; set it **false** before enabling the native `mars -> backup` timer so exactly one off-site transport is active. The root job continues its local backup work when the remote phase is disabled.

Rollback is non-destructive: disable any separately enabled schedule first, set opt-ins false and redeploy. Do not delete `diaries-backup`, `.diaries-backup-generations`, legacy backup trees, verified markers for still-current mirrors, Snapper media or native read-only snapshots merely to roll code back.

## 0034 Step 10 Item 4 — mars source snapshot readability

This is **opt-in** (`diaries_snapshot_source_acl_enabled: false` by default).
It grants the configured normal account read/traverse (`rX`) ACLs to the
*mutable* `/media/usb/@data/backup` tree and sets default directory ACLs
for newly created content. No write ACL is granted. It can be expensive on
a large source tree: plan a maintenance window. Existing read-only snapshots
are **not** changed and can remain unreadable. Take a NEW timestamp-named
read-only `@data` snapshot after the source ACL is installed; check marker
and complete-tree access through `ssh mars` as `richard@backup`.

Never make the historical snapshot temporarily writable or recursively
`chmod` source backups. Keep automatic backup snapshot activation disabled
until live readability and transfer verification pass.

## 0034 Step 11.4 unattended Diaries collection

`diaries-pull.timer` is installed only with the permanent pull helper and is default-off.
Enabling it requires both `diaries_pull_install: true` and
`diaries_snapshot_integration_enabled: true`. The legacy-rsync switch is independent of
the `pluto -> mars` pull; it must be false before the native **off-site push** timer is
enabled. The default pull calendar is 01:30 UTC,
after the suggested 00:30 UTC production publication and before a later hourly native
snapshot. The service runs as the normal administrative account and remains serialized
by the existing whole-backup writer lock. Use `systemctl status`/`journalctl` as the
operational record; a failed service must not be treated as snapshot-eligible.


## Native Btrfs snapshot management

The permanent `backup-collection.yaml` entry point includes the shared
`snapshots` role for native timestamp-named Btrfs snapshots.

Legacy Snapper and the `btrfs-legacy-prune` systemd units were retired
during 0040-FEAT. Their installation, activation and rollback procedures
are no longer applicable. Historical migration evidence is retained in
change-control records.

The focused `--tags snapshots` deployment manages native snapshot
configuration without deploying unrelated Diaries components. Review a full `--check` before accepting a complete
`backup-collection.yaml` deployment; avoid exposing rendered configuration with `--diff`.

## 0045 operator entry points

Use `backup-collection.yaml` or `scripts/backup-collection.sh` for a normal full
backup-collection deployment on `mars`. Use `btrfs-replication.yaml --limit backup`
for receiver-side deployment. The role was renamed from `local-backup` in 0047-FEAT. Installed root/user backup scripts,
including `/root/scripts/backup/remote/`, remain unchanged.

## Git-native source permissions (0048-FEAT)

`install_user_scripts.yaml` and `install_machine_scripts.yaml` use archive-mode
`ansible.posix.synchronize`, with `--omit-dir-times` and no `--chmod` or
`--no-perms`. Directory and file modes for synchronized content come from the
**actual controller checkout**, not a separately restored historical manifest.
The user directory-creation task leaves synchronized directories' modes
unspecified; the independent user `cron` and `log/backup` directories remain
`0750`. The machine directory task retains its previous no-mode behaviour.
Backup launcher templates continue to be installed separately with mode `0744`.

For the accepted Git checkout on `mango` (umask `022`), the five synchronized
source directories have mode `0755` and the nine include/exclude files have
mode `0644`. Git does not store directory modes or group-write bits; these
modes therefore depend on checkout environment. Before deploying, run:

```bash
cd /home/richard/ansible-controller/playbooks
python3 roles/backup-collection/tests/verify-collection-source-modes.py
```

The preflight checks current source metadata and role policy, but does **not**
modify files or deploy anything. If a checkout has different permissions,
inspect its environment and compare it with a clean Git checkout instead of
blindly running a historical `chmod` restoration. In particular, rsync will
copy the modes actually present in the source checkout. The accepted `mars`
parent-directory boundaries remain `/home/richard` (`0750`) and `/root`
(`0700`); do not relax those boundaries as part of this role.

The historical source-mode manifest and manual restoration procedure were
retired from active Playbooks by 0048-FEAT. Their audit trail remains under
the completed Diaries `0047-FEAT` change-control directory. Production
acceptance and rollback evidence are recorded separately by 0048; the source
policy alone does not establish that a deployment has passed.
