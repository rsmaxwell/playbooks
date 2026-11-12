# 0034-FEAT Step 9 — deploy on `pluto` without destroying existing backups

This directory contains the controlled production migration/acceptance tooling for Step 9. It deliberately separates **deployment** from **backup/publication**. Ordinary `diaries.yaml` deployment still installs configuration and scripts only and never starts a backup, publication, rsync, snapshot or restore.

## Contract being deployed

- Legacy completed backups remain under `/home/richard/projects/diaries/data/dataset-backups/production/<backupId>` and are not moved, rewritten or pruned.
- The final stable publication is `/home/richard/projects/diaries/data/diaries-backup`, outside the legacy repository and restore-state tree.
- The transitional Step 6 pilot path `/home/richard/projects/diaries/data/dataset-backups/production/diaries-backup` is evidence/media from the pilot. Step 9 does not delete it.
- Plain `scripts/backup-dataset.sh` remains the frozen 0033 capture-only command.
- `scripts/backup-dataset.sh publish-preflight` is read-only and checks both the publisher layout and live capture preflight.
- `scripts/backup-dataset.sh publish` creates a normal verified timestamp-ID backup first, then publishes that exact completed backup. If publication fails, the completed timestamp-ID backup remains valid and the previous stable publication remains selected.

No Docker image rebuild is required for Step 9 because only Playbooks Python/YAML/Markdown and change-control documentation change.

## 1. Source regression on `mango`

Run from the Playbooks repository root:

```bash
python3 roles/diaries/tests/verify-complete-dataset-manifest.py
python3 roles/diaries/tests/verify-complete-dataset-publisher.py
python3 roles/diaries/tests/verify-complete-dataset-replication.py
python3 roles/diaries/tests/verify-production-backup-restore-semantics.py
python3 roles/diaries/tests/verify-production-btrfs-strategy.py
python3 roles/diaries/tests/verify-production-complete-dataset-tooling.py
python3 roles/diaries/tests/verify-production-publication-contract.py
python3 roles/diaries/tests/verify-production-publication-wiring.py
python3 roles/diaries/tests/verify-production-restore-source-compatibility.py
python3 roles/diaries/tests/verify-production-storage-isolation.py
python3 roles/diaries/tests/verify-production-deployment-contract.py
python3 roles/local-backup/tests/verify-diaries-pull.py

python3 -m py_compile \
  roles/diaries/files/sync/scripts/production-complete-dataset.py \
  roles/diaries/tests/verify-production-publication-wiring.py \
  verification/0034-step9/verify-pluto-rsync-lock.py
```

Every suite must pass before production deployment.

## 2. Read-only predeploy inspection, then private safety capture

First inspect without changing `pluto`:

```bash
ansible-playbook verification/0034-step9/capture-predeploy.yaml
```

Then persist the Step 9 safety capture on `pluto`:

```bash
ansible-playbook verification/0034-step9/capture-predeploy.yaml \
  -e step9_capture=true
```

The playbook reports a private directory such as:

```text
/home/richard/projects/diaries/data/0034-step9-safety/<UTC timestamp>
```

Record that exact path as `STEP9_SAFETY_DIR`. It contains the predeploy `.env` (0600), its checksum, non-secret backup contract, historical backup ID inventory, publication-path inventory, backup preflight and deployment state. Do not check the saved `.env` into Git or evidence because it contains production secrets.

## 3. Deploy through normal Playbooks

From `mango`:

```bash
./scripts/diaries.sh
```

This must remain a configuration/tool deployment only. It must not create or delete any complete backup or publication generation.

## 4. Verify deployment preserved all historical backups

Immediately after deployment and **before making a new Step 9 backup**:

```bash
ansible-playbook verification/0034-step9/verify-postdeploy.yaml \
  -e step9_safety_dir="$STEP9_SAFETY_DIR"
```

Acceptance requires:

- exact pre/post legacy timestamp-ID inventory equality;
- deployed `DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT=/home/richard/projects/diaries/data/diaries-backup`;
- `backup-dataset.sh publish-preflight` succeeds without mutation;
- at least one preserved historical ID passes `restore-dataset.sh preflight`;
- the transitional Step 6 pilot path remains explicitly restorable when present; and
- the private predeploy `.env` safety copy is checksum-valid. The playbook copies it to a disposable rollback-demo file, proves the checksum, then removes only that disposable copy. It never replaces the live `.env`.

If this stage fails, stop. Do not create a new backup or publication until the difference is understood.

## 5. Create and publish the first final-path production generation

SSH to `pluto` as the normal operator and run:

```bash
cd ~/projects/diaries
./scripts/backup-dataset.sh publish-preflight
./scripts/backup-dataset.sh publish
./scripts/complete-dataset-publisher.py \
  --published-root "$PWD/data/diaries-backup" \
  verify-current
./scripts/complete-dataset-publisher.py \
  --published-root "$PWD/data/diaries-backup" \
  show-current-id
./scripts/restore-dataset.sh preflight diaries-backup
```

Record the first published ID as `FIRST_ID`. Confirm the same ID still exists as the legacy directory:

```bash
test -d "$PWD/data/dataset-backups/production/$FIRST_ID"
```

Do not remove the legacy directory or the transitional Step 6 pilot publication.

## 6. Create a second complete backup without publishing it yet

Run the frozen capture-only command:

```bash
cd ~/projects/diaries
./scripts/backup-dataset.sh preflight
./scripts/backup-dataset.sh
```

Record the new ID as `SECOND_ID`. It must differ from `FIRST_ID`. Before the lock proof, the stable `diaries-backup` must still report `FIRST_ID`.

## 7. Prove real rsync cannot mix generations, and publish the second backup

From `mango`:

```bash
ansible-playbook verification/0034-step9/run-rsync-lock-proof.yaml \
  -e step9_run=true \
  -e step9_candidate_id="$SECOND_ID"
```

This is intentionally the mutating acceptance test. On `pluto` it:

1. verifies the current published first generation and the second legacy candidate;
2. starts a real `rsync -a --delete` of the stable path into a disposable local scratch tree while holding the same shared `.diaries-backup.lock` contract used by the `mars` pull;
3. attempts to publish `SECOND_ID` concurrently and requires the publisher to remain blocked while rsync is active;
4. verifies the received scratch tree as the complete `FIRST_ID` schema-2 dataset, proving no generation mixing;
5. requires publication to advance to `SECOND_ID` only after rsync releases the shared lock;
6. requires the immutable `FIRST_ID` generation to remain retained; and
7. removes the disposable scratch tree on success. On failure it retains the scratch path for diagnosis.

After PASS:

```bash
cd ~/projects/diaries
./scripts/complete-dataset-publisher.py \
  --published-root "$PWD/data/diaries-backup" \
  verify-current
./scripts/restore-dataset.sh preflight diaries-backup
./scripts/restore-dataset.sh preflight "$FIRST_ID"
./scripts/restore-dataset.sh preflight "$SECOND_ID"
```

All three source forms must remain valid.

## Rollback rule

A Step 9 code/config rollback must be non-destructive: revert the Playbooks source/commit and redeploy configuration, or restore the saved predeploy `.env` only as an explicitly reviewed emergency action. **Never** delete the final-path stable publication, immutable generation store, transitional Step 6 publication, timestamp-ID repository, restore state or any later 0035 snapshots as part of code rollback. If reverting the published-root setting, leave both paths in place until the intended restore/replication source has been independently verified.

## Step 9 closure evidence

Do not mark Step 9 closed until the following runtime evidence has been captured:

- source regressions PASS on `mango`;
- predeploy safety directory path and non-secret inventory output;
- normal Diaries Ansible deployment result;
- postdeploy exact legacy inventory comparison PASS;
- first `publish` output and `FIRST_ID`;
- second capture output and distinct `SECOND_ID`;
- live rsync/publication contention proof PASS;
- final `verify-current` and restore preflights for `diaries-backup`, `FIRST_ID`, and `SECOND_ID`; and
- rollback-copy demonstration PASS.

## Step 9 correction after first publication (2026-10-09)

The initial first-generation `publish` completed successfully, but the next
`publish-preflight` exposed a stable-path symlink resolution bug: the runtime
resolved `data/diaries-backup` to its `.diaries-backup-generations/<backupId>`
target before invoking the publisher, which requires the stable root name
`diaries-backup`. The runtime now retains the configured lexical absolute path
rather than dereferencing the stable publication symlink. No existing backup
or published generation should be deleted or recreated to remedy this.

The original strict predeployment inventory equality remains the default.
After the first publication, explicitly allow *additional* backup IDs while
still requiring every predeployment ID to remain:

```bash
ansible-playbook verification/0034-step9/verify-postdeploy.yaml \
  -e step9_safety_dir=/home/richard/projects/diaries/data/0034-step9-safety/20261009-152441Z \
  -e '{"step9_allow_new_backups": true}' --ask-vault-pass
```

Deploy only the changed Playbooks scripts/config through the regular diaries
playbook, then rerun `./scripts/backup-dataset.sh publish-preflight` on `pluto`.
This is non-destructive. Do not run `publish` again just to confirm this fix.
