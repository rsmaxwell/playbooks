# 0040-FEAT Step 11 — Hold migration cutover / rollback (REVIEW ONLY)

**NOT AUTHORISED TO EXECUTE.** The source-only package does not alter mars. Existing root snapshots, replication protection, and receiver pruning remain untouched.

## Preconditions / gate

- Accepted production evidence: 63 historical root snapshots; 64 @data snapshots at 20:06 UTC Oct 25; 0 incomplete; 2 holds; receiver CLEAN; `receiver_prune_enabled: false`.
- Review `commit-checkpoint-hold-migration.py` and its tests in Beyond Compare. Candidate Ansible desired state in `/etc/ansible/host_vars/mars/backup.yaml` must remove the `root` entry entirely and retain `@data` required/creation/prune all true. Do **not** apply new Ansible config until holds migrated.
- Before authorising change: ensure an existing recoverable offsite @data checkpoint and both protected replication timestamps; assess whether to stop native replication timer for the few-minute maintenance window to prevent concurrent transfers.
- Take a fresh read-only baseline: sha256 of `/etc/btrfs-snapshot-manager.json`, original hold file, root/@data subvol counts, `hold-list`, snapshot manager status, prune --dry-run, and systemctl timers. Capture outputs as evidence.
- Explicitly authorise only the hold-file migration. **Root deletion needs a separate approval.**

## Proposed controlled sequence (NOT copy/paste operational command; requires review)

1. On **mars SSH terminal**, stop both `btrfs-snapshot-create.timer` and `btrfs-snapshot-prune.timer`; ensure creation and prune services have exited. Do **not** disable the timers permanently. Check other snapshot/replication jobs and maintenance lock state.
2. On **mango SSH terminal**, stream the `commit-checkpoint-hold-migration.py` utility with **no `--commit`** first to preview and verify old UUIDs. Preserve output.
3. Acquire an approved maintenance window; invoke the script with `--commit --authorise 0040-STEP11-HOLDS-ONLY` over SSH; it checks both timers/services inactive, acquires manager lock, validates both historical root and @data UUIDs, writes an exclusive 0600 rollback file, atomically replaces the holds file, and reports both SHA-256 hashes. Script never deletes subvolumes.
4. **Without running snapshot-manager commands while config/holds are inconsistent**, edit desired source list in `/etc/ansible/host_vars/mars/backup.yaml` to @data-only, run Ansible syntax/check-diff (note status preflight is skipped in check mode), and deploy `snapshots.yaml --limit mars --tags snapshots --vault-password-file ~/.vault_pass.txt` from **mango SSH terminal**. Its live preflight must succeed.
5. Validate `hold-list` presents both historical timestamps, `status` reports zero incomplete sets, Diaries verification remains valid, and `prune --dry-run` excludes protected/held items and proposes no root deletions. Verify Ansible idempotency, timer state, and receiver pruning remains off.
6. Preserve original hold backup and old configuration under historical evidence storage until separately approved cleanup. **Do not delete any root snapshots.**

## Rollback (before services resume)

If the hold migration completes but Ansible deployment or preflight fails, keep snapshot timers stopped. Restore prior two-source configuration and original hold records *as a matched pair*. Restoration must use validated content from `.checkpoint-holds.0040-step11-before.json`, preserve root ownership and 0600 permissions, and use an atomic same-directory replacement. Verify `hold-list`, `status`, and dry-run under old config before resuming timers. Never resume normal pruning in an inconsistent intermediate state. The separate `rollback-checkpoint-hold-migration.py` utility is preview-only by default; after restoring the two-source manager configuration, and with both snapshot timers/services stopped, it can restore the validated original backup with `--commit --authorise 0040-STEP11-ROLLBACK-ONLY`. Its real production invocation is NOT authorised by this source review. Recheck status, holds and pruning dry-run before resuming.

## Deferred

Root snapshot retirement is a separate deletion gate. It must review the root inventory and dependencies; preserve both @data checkpoint holds and replication protection. Receiver pruning stays disabled until its independently approved stage.

## Source regression before production approval

On mango (read-only fixtures, no Btrfs access):

```bash
cd /home/richard/playbooks
python3 roles/snapshots/tests/0040-step11/verify-preview.py
python3 roles/snapshots/tests/0040-step11/verify-commit-rollback.py
python3 -m py_compile roles/snapshots/tests/0040-step11/*.py
git diff --check
```

A passing disposable regression does not authorise production commit. Preserve original hold backup and do not delete historical root snapshots.
