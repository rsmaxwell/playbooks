# Diaries Ansible role

This role deploys the production Diaries Compose stack. Production durable storage follows the same invariant as local development:

```text
one effective database dataset <-> one effective mutable Files root
```

## Mutable Files selector

Inventory must define:

```yaml
diaries_files_dir: files
```

for the current production dataset. `diaries_files_dir` deliberately has **no role default**. `roles/diaries/tasks/main.yaml` requires one non-empty leaf directory name containing no path separators or whitespace. The template renders it as:

```text
DIARIES_FILES_DIR=<diaries_files_dir>
```

The responder mount then selects:

```text
${DIARIES_NAS_CONTENT_PATH}/${DIARIES_FILES_DIR} -> /data/files
```

The original diary-page scan tree remains separate and read-only:

```text
${DIARIES_NAS_CONTENT_PATH}/diaries -> /data/diaries:ro
```

`diaries_files_dir` is therefore a physical storage selector, not a browser namespace. The responder continues to serve uploaded/catalogued content under `/files/...`, and persisted `Image.relativePath` values remain relative to the selected Files root. Do not place deployment/environment names into persisted paths.

Production does not use the local `config/environments/local.env` override mechanism. The role's explicit inventory variable is the production source of the mutable Files selector. Before deployment, review the rendered `.env`/Compose output and confirm the selected Files root is paired with the intended production PostgreSQL volume/dataset.

## ImageFragment production authoring gate

The responder authoring gate is rendered from one explicit role variable:

```yaml
diaries_image_fragment_writes_enabled: true
```

With 0027 completed, the role default is deliberately `true`. IMAGE Fragment creation and Image-reference attach/replace/clear are now normal supported Diaries functionality, and production verification on `pluto` completed the enabled lifecycle with client `0.0.9-build-76`, responder `0.0.9-build-84` and reader `0.0.9-build-8`.

The gate remains an important responder-side safety and non-destructive rollback control. Setting:

```yaml
diaries_image_fragment_writes_enabled: false
```

and redeploying/restarting the responder stops new IMAGE Fragment creation and actual Image-reference mutations with 403 responses. It does **not** remove existing IMAGE data, and ordinary IMAGE reads, text/date/sequence edits, locking, normalisation and Fragment deletion remain available because those operations omit/preserve `imageId`.

The generated `config/responder/responder.json` must reflect the effective Ansible value. A target may override the role default in inventory when a temporary authoring stop is required; returning the override to `true` restores normal authoring after the underlying reason has been resolved. No database or Files rollback is required merely to toggle this gate.

The production `diaries-client` MQTT identity must also have narrow read access to `diaries/images/+`. IMAGE Fragments resolve `imageId` through those retained catalogue metadata topics; RPC access and Fragment-topic access are not sufficient. Mosquitto file ACLs may acknowledge a subscription while silently withholding unauthorized retained messages, so the permanent deployment-contract regression verifies this client permission explicitly.

## Changing storage selection

Changing only the production database dataset or only `diaries_files_dir` is invalid unless the operator is deliberately restoring/reconciling a known matched pair. Never use the local common root or any `files-development-*` directory for the production database.

If a future production migration changes `diaries_files_dir`, treat that as a durable-data migration: freeze responder writes, back up the current matched database + Files pair, reconcile the target root, deploy the explicit selector, and verify database/catalogue/Files consistency before writes resume.

Do not temporarily re-point independently changed datasets to one shared Files directory as a rollback shortcut. Preserve isolated roots until reconciliation is complete.


## Production helper lifecycle

`roles/diaries/files/sync/scripts/` is reserved for permanent supported production operator tooling. The deployed `{{ diaries_project_dir }}/scripts/` directory is a **managed directory**: it is synchronized separately with `rsync --delete --delete-excluded`, while the permanent templated operator scripts are explicitly protected and then rendered by Ansible. Any other stale or feature-specific entry left in the deployed scripts directory is therefore removed automatically on the next normal copy deployment.

Temporary feature-only migration, capture or verification helpers must be explicitly deployed for the feature and explicitly removed during feature close-out; they must not accumulate in the permanent synchronized source set. If a feature temporarily installs a helper directly on production, the next normal managed-script synchronization also provides a safety net by deleting it unless it has been deliberately classified as permanent source or a protected permanent template.

The project-root synchronization deliberately excludes `scripts/`, so `--delete` is never applied to the wider Diaries project directory. The permanent `roles/diaries/tests/verify-production-deployment-contract.py` regression enforces this scope, the approved synchronized script set, the protected template set and the absence of unclassified feature/step-shaped helpers. Completed temporary tooling should be preserved, when needed, with the corresponding Diaries change-control evidence rather than left in the role.

## Backup and restore

### Choose the backup type

The installed `scripts/backup-db-*` and `scripts/restore-db-*` helpers remain **database-only** operations. Use them only when the intended unit of work is PostgreSQL and the operator is separately controlling the matching mutable Files state. New database backups carry a `.dataset.json` sidecar recording the production Files selector/root, but that sidecar does not contain Files bytes.

Use the permanent **complete-dataset** command for disaster recovery, durable rollback points, before risky database+Files changes, and whenever the backup is expected to recover the whole mutable Diaries dataset without a separately managed Files snapshot:

```text
scripts/backup-dataset.sh preflight
scripts/backup-dataset.sh
```

The complete-dataset boundary is PostgreSQL durable application data plus the matching mutable Files root. It deliberately excludes the shared read-only original diary scans, MQTT retained topics (rebuilt from PostgreSQL), Docker/application images, `.env`/credentials/Mosquitto secrets and wider NAS/platform backups.

### Production backup operation

Complete backups use the schema-2 directory/manifest contract shared with local tooling. Their repository and restore-state locations are explicit Playbooks inputs rather than paths inferred by the Python engine:

```yaml
diaries_complete_backup_repository_root: "{{ diaries_project_dir }}/data/dataset-backups/production"
diaries_complete_restore_state_root: "{{ diaries_project_dir }}/data/dataset-restores/production"
diaries_complete_backup_storage_mode: auto
```

The generated `.env` exposes these as `DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT`, `DIARIES_COMPLETE_RESTORE_STATE_ROOT` and `DIARIES_COMPLETE_BACKUP_STORAGE_MODE`. The defaults deliberately preserve the completed 0033 ext4 layout, so Step 2 does not relocate existing media. Inventory may later override the repository root when the Btrfs repository is provisioned. The backup and restore-state roots must be distinct absolute host paths and are separate from the mutable NAS Files tree. The effective Files identity continues to come from deployed `.env` (`DIARIES_FILES_DIR`, rendered from `diaries_files_dir`) and the actual Docker volume mounted at responder `/data/files`.

The storage mode accepts exactly `auto`, `required-btrfs` or `full-copy`. Step 2 freezes and validates that configuration contract; the production capture path deliberately remains the frozen 0033 full-copy implementation until Step 3 adds capability probing and effective strategy selection.

Always run `preflight` first. It is non-destructive and reports the logical dataset, database identity, Files selector/root, Docker NAS volume, responder state and `.image-staging` disposition. The real backup quiesces only `diaries-responder`, keeps PostgreSQL available, captures both dump formats plus the durable Files tree excluding transient `.image-staging`, rereads and hashes the source, writes inventory/checksum evidence, validates schema-2 media, atomically promotes the `.partial` directory and only then restores the prior responder-running state.

The expected application downtime is therefore the controlled responder-quiescence interval covering PostgreSQL dump capture, Files copy and source/media verification. If capture/finalisation fails after quiescence, the responder is deliberately left stopped and the `.partial` media is non-restorable until an operator diagnoses the failure.

Verify any completed production backup independently before treating it as recovery media:

```text
python3 scripts/complete-dataset-manifest.py verify \
  --backup-dir <configured-complete-backup-repository-root>/<backup-id>
```

Normal verification must target the promoted `<backup-id>` directory, not a `.<backup-id>.partial` workspace. The validator rechecks schema/completion state, safe component paths, database hashes and the exact Files inventory/hashes.

### Production complete restore

The production restore interface is deliberately phased:

```text
scripts/restore-dataset.sh preflight <backup-id|diaries-backup|directory>
scripts/restore-dataset.sh prepare <backup-id|diaries-backup|directory>
scripts/restore-dataset.sh apply <backup-id|diaries-backup|directory>
scripts/restore-dataset.sh postflight <backup-id|diaries-backup|directory>
# if recovery is required before accepted postflight:
scripts/restore-dataset.sh rollback <backup-id|diaries-backup|directory>
```

`preflight` is read-only. `prepare` requires the exact `RESTORE` confirmation, stops the responder, creates and independently validates a fresh **complete-dataset safety backup**, and stages a verified sibling Files replacement without changing the live pair. `apply` requires `APPLY`, restores only `database/diaries.dump` (the SQL dump remains a companion representation), moves the old live Files tree to an explicit rollback sibling and promotes the staged tree by same-volume rename. This is replacement/exact semantics, never merge semantics; stale `.image-staging` payloads are not restored.

The source selector is backward compatible. A UTC `<backup-id>` still selects the historical directory beneath `diaries_complete_backup_repository_root`. `diaries-backup` (with or without a trailing slash) selects the separate stable fixed publication at `diaries_complete_backup_published_root`. An absolute or explicit directory path selects any independently accessible completed schema-2 dataset, including a read-only snapshot path returned by the future 0035 `diaries-backup-history path BACKUP_ID` command. `diaries-backup-history` is discovery/verification only: it must never start a destructive restore. Always copy or type its returned path into a separate `restore-dataset.sh preflight ...` command first.

`prepare` records the resolved immutable source directory. Subsequent `apply`, `rollback` and `postflight` by bare backup ID prefer that prepared source, so advancing the fixed `diaries-backup` pointer cannot change an in-progress recovery. The selected path must still exist and verify; otherwise the restore stops rather than falling back to different media.

After `apply`, the responder remains stopped. `postflight` verifies database/Image counts, exact Files inventory, Image catalogue/Files reconciliation, responder health, retained MQTT replay, representative retained MARQUEE/IMAGE objects and representative `/files` bytes. Only then is the prior responder-running state restored and automatic rollback closed. A failed postflight leaves the application stopped/non-writable with the verified safety backup and pre-restore Files tree available to `rollback`.

The Ansible role **deploys** this tooling and never schedules a destructive complete restore. Complete-backup publication remains default-off and runs automatically only when the Step 11.4 scheduling opt-in is explicitly enabled. Production restore was proven destructively in the disposable Step-9 rehearsal; routine production rollout requires only non-destructive backup verification unless an actual recovery event requires restore.


## 0034 complete-backup publication configuration

Step 8 adds `diaries_complete_backup_published_root`, defaulting to `{{ diaries_project_dir }}/data/diaries-backup`. It is a stable atomic publication path and must remain distinct/non-overlapping with both the legacy timestamp-ID repository (`diaries_complete_backup_repository_root`), the restore-state root (`diaries_complete_restore_state_root`), and any locally-resolved mutable source Files root. The generated `.env` exports it as `DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT`.

The older `diaries_complete_backup_storage_mode` values remain supported because historical 0033/0034 capture/preflight compatibility is still required. Direct reflink publication on `pluto` is superseded; do not delete its regression silently. With the Step 11.4 scheduling flag left at its default `false`, normal role deployment creates/renders configuration and installs tools only—it does not capture, publish, replicate, snapshot or restore a dataset. Step 9 added explicit `backup-dataset.sh publish-preflight` and `backup-dataset.sh publish` modes; Step 11.4 may invoke those same supported modes from a default-off systemd timer. Plain `backup-dataset.sh` deliberately remains the frozen capture-only command.

## 0034 Step 11.4 unattended complete-backup publication

The role now installs `diaries-complete-backup-publish.service` and `.timer`. The timer
is deliberately default-off (`diaries_complete_backup_schedule_enabled: false`) so a
normal code deployment still does not start a backup. Once explicitly enabled in
production inventory, the service runs the permanent `backup-dataset.sh publish-preflight`
and `publish` commands as the normal administrative user and records the result in the
systemd journal. The default proposed calendar is 00:30 UTC and is configurable through
`diaries_complete_backup_on_calendar`.

This is backup creation/publication only; it never restores data. A failed complete
backup retains the existing fail-closed responder behaviour and must be visible as a
failed systemd service. Step 11.4 acceptance also requires the downstream `mars` pull,
native snapshot timers and source-initiated off-site push to be independently scheduled
and verified, with no simultaneous legacy rsync off-site transport.
