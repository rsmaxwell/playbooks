# Diaries production storage and backup/restore scripts

This directory contains the supported production operator tooling installed by
the Diaries Ansible role. Completed feature-migration and verification helpers
are retained in change-control evidence rather than deployed as live commands.


## Production tooling lifecycle

This synchronized directory is a small allow-list of permanent production operator tooling. Adding a file here means declaring that command part of the supported ongoing production surface; `roles/diaries/tests/verify-production-deployment-contract.py` fails if the source set grows without an explicit supported classification.

The deployed production `scripts/` directory is managed separately from the project root. Its synchronize task uses `--delete` and `--delete-excluded`, so entries which are neither present in this static source directory nor explicitly protected permanent templates are removed from production. The protected files are the Ansible-rendered permanent commands (`start.sh`, `stop.sh`, `status.sh`, `logs.sh` and the `shell-prompt-*.sh` scripts); Ansible templates them after the managed static sync.

A **temporary feature-only production helper** must not be left indefinitely in this always-synchronized tree. When a feature genuinely needs one, it must be explicitly deployed for that feature and explicitly removed during feature close-out. The managed-directory deletion is an additional safety net: a forgotten deployed helper is removed by the next normal copy deployment unless it has been deliberately promoted into the permanent managed set. Historical source belongs with the completed change-control evidence rather than in this directory.

Feature/step-shaped names are additionally treated as suspicious by the permanent deployment-contract regression. A genuinely permanent command with such a name requires an exact documented exception as well as inclusion in the supported-script set.

## Supported installed commands

The role installs these persistent production helpers:

```text
backup-dataset.sh
backup-db-to-binary.sh
backup-db-to-sql.sh
complete-dataset-manifest.py
complete-dataset-postflight.py
complete-dataset-restore-stage.py
complete-dataset-verification.py
dataset-backup-manifest.py
production-complete-dataset.py
restore-dataset.sh
restore-db-from-binary.sh
restore-db-from-sql.sh
```

The `backup-db-*` and `restore-db-*` commands are **database-only** operations.
They do not back up or restore the mutable Diaries Files tree.

`backup-dataset.sh` and `restore-dataset.sh` are the permanent production complete-dataset commands introduced by 0033. They derive the production pair and the 0034 storage contract from the deployed `.env`, stop only `diaries-responder`, keep PostgreSQL available, and access mutable Files through the responder's actual Docker-managed `nas-photo` volume rather than assuming a second host NAS mount. Historical timestamp-ID media uses `DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT`; the stable current publication uses the separate `DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT`; restore preparation/state uses `DIARIES_COMPLETE_RESTORE_STATE_ROOT`; and the retained legacy capture setting `DIARIES_COMPLETE_BACKUP_STORAGE_MODE` accepts exactly `auto`, `required-btrfs` or `full-copy`. The role defaults preserve the historical `data/dataset-backups/production` and `data/dataset-restores/production` locations, but the Python engine no longer derives either path from the project layout. Host-bound Files snapshots are written by a root maintenance container, then explicitly returned to the invoking operator UID/GID before host-side hashing/manifest validation; `.image-staging` is removed/asserted absent at that boundary. Step 2 keeps the frozen 0033 capture-mode inputs. Step 3's direct reflink-on-pluto strategy is historical/superseded: its regression remains deliberately present to protect compatibility, but the stable publisher itself is filesystem-independent and the current production repository remains full-copy on ext4.

`restore-dataset.sh` supports `preflight`, `prepare`, `apply`, `rollback` and `postflight`. `prepare` requires the exact token `RESTORE`, creates a mandatory verified complete safety backup, and stages a sibling Files replacement while leaving the live pair unchanged. `apply` requires `APPLY`, restores only `database/diaries.dump`, swaps the staged/live Files directories by same-volume rename, and leaves the responder stopped. `postflight` verifies database counts, exact Files inventory, Image catalogue/Files reconciliation, retained MQTT replay and representative `/files` bytes before restoring the prior responder-running state and closing automatic rollback.

0034 Step 7 preserves the 0033 restore contract while widening only the source selector. A restore source may be a historical `<backup-id>` beneath `DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT`, the stable token `diaries-backup` / `diaries-backup/` resolved through `DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT`, or an explicit schema-2 directory path. The explicit-path form is the handoff from 0035 snapshot history: `diaries-backup-history path BACKUP_ID` returns a read-only dataset path, and the operator passes that path explicitly to `restore-dataset.sh`; the history command never invokes a restore. All source forms use the same schema-2 manifest verifier, target-identity checks, `RESTORE`/`APPLY` confirmations, safety backup and rollback machinery.

After `prepare`, later `apply`, `rollback` and `postflight` commands may safely use the backup ID printed by the restore tooling. The prepared restore state pins the exact resolved source directory. This prevents a newer `diaries-backup` publication, or a same-ID directory elsewhere, from silently changing the media used by an in-progress restore. If the pinned directory disappears, continuation fails closed.

`complete-dataset-manifest.py`, `complete-dataset-verification.py`, `complete-dataset-restore-stage.py` and `complete-dataset-postflight.py` are the shared schema/inventory validators used by the production orchestrator. Their media semantics are intentionally the same as the local Windows tooling.

## Production storage invariant

The production PostgreSQL dataset and mutable Files root are one durable pair:

```text
one effective database dataset <-> one effective mutable Files root
```

Inventory supplies the mutable leaf selector as `diaries_files_dir`; the role
renders it to `DIARIES_FILES_DIR`, and Compose maps
`${DIARIES_NAS_CONTENT_PATH}/${DIARIES_FILES_DIR}` to stable `/data/files`.
The separate `${DIARIES_NAS_CONTENT_PATH}/diaries` scan tree is shared and
read-only. `/files/...` URLs and persisted `Image.relativePath` values remain
environment-neutral regardless of the physical Files selector.

Before a destructive Image/File operation, database restore, reconciliation or
storage migration, inspect the deployed `.env`/Compose configuration and confirm
the effective database plus `DIARIES_FILES_DIR`. Changing only the database or
only the Files selector is invalid unless this is an intentional matched
restore/reconciliation operation.

Never point independently changed datasets temporarily at one old shared Files
root as a rollback shortcut. Preserve separate roots and reconcile explicitly.

## Database-only backup sidecars

A successful database backup writes a dataset sidecar next to the dump, for
example:

```text
diaries-production-YYYYMMDD-HHMMSS.dump
diaries-production-YYYYMMDD-HHMMSS.dump.dataset.json
```

The sidecar records the database identity, effective Files selector/root,
runtime image identity and Image/catalogue count. It explicitly records:

```text
backupType = database-only
completeDatasetBackup = false
filesSnapshot = null
```

Before a sidecar-backed restore changes PostgreSQL, the restore command verifies
that the sidecar Files selector/root still matches the current production
configuration. A mismatch is rejected. Legacy backups without a sidecar remain
usable, but the operator must verify the matching Files snapshot/root manually.

## Complete matched backup and restore

The frozen complete-backup directory contract is:

```text
<dataset-backup-root>/<logical-dataset>/<backup-id>/
    dataset-manifest.json
    database/diaries.dump
    database/diaries.sql
    files/
    verification/database.sha256
    verification/files.sha256
    verification/inventory.json
```

`backup-id` is UTC `YYYYMMDD-HHmmssZ`. Capture is assembled under `.<backup-id>.partial` and only promoted to `<backup-id>` after verification. Normal manifest validation rejects `.<backup-id>.partial`; `--allow-partial-workspace` exists only for the pre-promotion finalisation check. The complete manifest is schema-2, has `backupType=complete-dataset`, `completeDatasetBackup=true`, `status=complete`, and uses relative component paths. Resolved database/Files source identities may naturally contain host-specific values, but they are identity fields rather than component references.

A complete recoverable Diaries backup is an operational bundle containing:

```text
PostgreSQL dump
+ matching mutable Files snapshot/copy
+ dataset/path identity manifest
+ optional reconciliation/checksum inventory
```

Capture the database dump and mutable Files snapshot while responder writes are
frozen so they describe one durable state.

For a matched restore:

1. stop/freeze `diaries-responder` while keeping PostgreSQL available as needed;
2. verify the effective database and Files selector;
3. preserve the current database and Files root;
4. restore the Files snapshot associated with the selected database dump;
5. restore the database dump;
6. run read-only reconciliation/checksum checks;
7. restart the responder only after the pair is understood and consistent.

A database-only restore can be intentional, but it remains potentially in need
of Files reconciliation before destructive Image/File lifecycle operations.

## Normal production operating procedure

Choose the operation according to the recovery unit. `backup-db-to-*` / `restore-db-from-*` are intentionally database-only and require separate operator control of matching Files state. `backup-dataset.sh` / `restore-dataset.sh` are the supported full-data path for disaster recovery and durable rollback points.

For a normal production complete backup:

```text
./backup-dataset.sh preflight
./backup-dataset.sh
python3 ./complete-dataset-manifest.py verify \
  --backup-dir <configured-complete-backup-repository-root>/<backup-id>
./status.sh
```

The backup command stops only `diaries-responder` during the coherent capture/verification window and restores its previous running state only after the final promoted media validates. If the command fails after quiescence, do not simply restart the responder: inspect the reported `.partial` workspace and cause first.

For recovery, run `restore-dataset.sh preflight` before any mutation. `prepare` creates a mandatory verified complete safety backup and verified Files stage; `apply` restores the custom dump and exact Files tree; `postflight` is required before service is returned. Use `rollback` while automatic rollback remains open if apply/postflight cannot be accepted.

The complete backup does **not** include the read-only original diary scan tree, MQTT retained topics, Docker images/binaries, credentials/environment secrets or platform/NAS backups. `.image-staging` is transient: only the understood benign lock/empty state is accepted before capture, and staged payloads are not copied into complete backup media.

## Production complete-dataset commands

From the deployed `{{ diaries_project_dir }}/scripts` directory:

```text
./backup-dataset.sh preflight
./backup-dataset.sh
./backup-dataset.sh publish-preflight
./backup-dataset.sh publish

./restore-dataset.sh preflight <backup-id|diaries-backup|directory>
./restore-dataset.sh prepare <backup-id|diaries-backup|directory>
./restore-dataset.sh apply <backup-id|diaries-backup|directory>
./restore-dataset.sh rollback <backup-id|diaries-backup|directory>
./restore-dataset.sh postflight <backup-id|diaries-backup|directory>
```

Ansible only deploys these commands; it never invokes a complete restore during normal rollout. A failed capture/finalisation or failed restore postflight leaves `diaries-responder` stopped so an operator can inspect or roll back. PostgreSQL and MQTT are not routinely stopped by the complete-dataset tooling.


## 0034 stable publication and replication operations

An Ansible deployment leaves all Step 11.4 schedules disabled unless production inventory explicitly opts in. It never schedules a restore. Step 9 wires the producer through supported modes: plain `backup-dataset.sh` keeps the frozen 0033 timestamp-ID capture-only behaviour, while `backup-dataset.sh publish-preflight` checks both the publisher layout and live capture preflight without mutation, and `backup-dataset.sh publish` creates a normal immutable timestamp-ID backup first and publishes that exact completed backup only after capture verification succeeds. When the Step 11.4 publisher timer is explicitly enabled it invokes the latter two modes unattended.

The stable publication path is `DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT` (default `<diaries_project_dir>/data/diaries-backup` in role source). Its sibling `.diaries-backup-generations/` directory is the immutable generation store and `.diaries-backup.lock` is the shared publisher/reader lock. Do not place the published root inside the legacy timestamp-ID repository or restore-state tree.

### Production capture + publication

For normal Step 9 production use, run `backup-dataset.sh publish-preflight` first and then explicitly run `backup-dataset.sh publish`. The latter preserves the completed timestamp-ID backup under `DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT`, copies/verifies it into the immutable generation store beside `DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT`, atomically advances the stable `diaries-backup` pointer, verifies the new current generation and prints the selected backup ID.

Plain `backup-dataset.sh` remains capture-only for historical compatibility and for the Step 9 second-backup concurrency rehearsal. An operator may still invoke `complete-dataset-publisher.py` directly for a reviewed already-completed candidate, but this is an expert recovery/testing path rather than the normal producer command.

If publication fails after a successful capture, the new timestamp-ID backup remains valid historical media and the previously selected stable generation remains current. Diagnose the publisher failure before retrying; do not delete or overwrite the completed legacy backup to force publication.

A duplicate `backupId` is a hard error. Never overwrite or rename an existing generation to force reuse of an ID. Determine whether the duplicate is the same completed media, create a genuinely new capture with a new UTC ID if needed, and preserve the previous current generation until the operator has verified the replacement.

### Abort and failure behaviour

A failed candidate verification or interrupted pre-publication copy must leave the existing public pointer unchanged. After any error, run `verify-current`; if it succeeds, the last-good generation remains the recovery source. Do not delete `.staging-*`, `.diaries-backup-link.*` or generation directories while a publisher/reader may be active. If a process has definitely exited and temporary artefacts remain, record them first and remove only the identified temporary artefact—not the current symlink target or historical backups.

Receiver transfers use a private temporary incoming directory and `rsync --delete` only within that new tree. The receiving manifest is verified before the receiving publisher is changed. A transfer failure must therefore leave the previous receiving publication intact, and every 0034 handoff remains `snapshotEligible=false` until 0035 performs its separate whole-backup acceptance.

### Disk pressure and cleanup

There is intentionally no automatic generation-retention policy in 0034 Step 8. Check `df`/`du` before publication and replication. Under pressure, first remove abandoned temporary workspaces that are proven inactive. Retired immutable generations may be removed only after confirming they are not the current symlink target, not pinned by an active reader, not required for rollback/rehearsal, and not the only copy of a required backup ID. Legacy `<backup-id>/` directories are outside this cleanup policy and must not be silently pruned by the publisher.

### Source synchronization and rollback

The Playbooks role source is authoritative for deployed production scripts. The deployment regression intentionally rejects unclassified feature/step helpers, and the managed script directory removes stale unmanaged commands. Keep change-control-only verification tools in evidence/verification rather than promoting them to production scripts.

Rollback of Step 8 source is configuration-only: stop/disable any separately arranged pull schedule first, revert the Playbooks commit, and redeploy. Do not remove the last-good stable publication, immutable generations, legacy backup IDs, restore state or 0035 snapshots as part of code rollback. If reverting `DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT`, preserve both old and new paths until the selected current generation has been verified from the intended location.
