# 0034-FEAT Step 8 — source regression

Run the following from the Playbooks repository on `mango`. Keep each command separate so its transcript identifies the exact suite that passed or failed:

```bash
python3 roles/diaries/tests/verify-complete-dataset-manifest.py
python3 roles/diaries/tests/verify-complete-dataset-publisher.py
python3 roles/diaries/tests/verify-complete-dataset-replication.py
python3 roles/diaries/tests/verify-production-backup-restore-semantics.py
python3 roles/diaries/tests/verify-production-btrfs-strategy.py
python3 roles/diaries/tests/verify-production-complete-dataset-tooling.py
python3 roles/diaries/tests/verify-production-publication-contract.py
python3 roles/diaries/tests/verify-production-restore-source-compatibility.py
python3 roles/diaries/tests/verify-production-storage-isolation.py
python3 roles/diaries/tests/verify-production-deployment-contract.py
python3 roles/local-backup/tests/verify-diaries-pull.py
```

This is source-only. It covers schema/manifest, publication/concurrency, receiver validation, backup/restore, the deliberately retained historical Step 3 strategy contract, complete tooling, stable-publication path isolation, legacy/fixed/snapshot restore compatibility, storage isolation, deployment contract, and `mars` pull ownership/delete scope.

The historical `verify-production-btrfs-strategy.py` suite is intentionally retained: Step 8 supersedes reflink publication but preserves the Step 2 storage-mode contract until a separately documented migration retires it.

A PASS does not authorize production deployment, cron activation, transfer, snapshotting, cleanup or restore. Step 9 owns the non-destructive `pluto` deployment and publication acceptance.
