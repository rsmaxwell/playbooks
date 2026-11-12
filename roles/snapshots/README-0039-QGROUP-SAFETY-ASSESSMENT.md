# 0039-DEF Step 3 — offline qgroup safety assessment

This diagnostic is **not a deletion plan**. It accepts only existing complete JSON manifests and filesystem identity evidence; no Btrfs commands, network calls, quota actions or filesystem mutation are used. It invokes the adjacent `validate-qgroup-manifest.py` to independently verify the complete saved inventory first.

Run source regressions on `mango`:

```bash
cd /home/richard/playbooks
python3 roles/snapshots/tests/verify-qgroup-safety-assessment.py
python3 roles/snapshots/tests/verify-qgroup-manifest-validator.py
python3 -m py_compile roles/snapshots/files/assess-qgroup-safety.py
```

The CLI requires `--manifest`, `--identity`, `--expected-host`, `--expected-uuid` and repeatable `--protected-id` numeric **active subvolume IDs**. Each protected ID must exist in the manifest's active subvolume inventory and have an active level-zero qgroup; absent, duplicate and inactive values fail closed. These supplied IDs are a **partial and independently determined set**, not proof that all retention, replication and historical dependencies have been identified. Use the verified IDs from the defect's Step 3 protection evidence, not speculative IDs.

Classifications are exclusion-oriented: active, limited, related, pending deletion, higher-level, and ambiguous records are excluded from investigation. The remaining unmatched entries are **investigation only** — explicitly not safe-to-remove. Output includes small samples and totals, the source inventory fingerprint, `deletion_authorized: false` and an empty `deletion_commands` list. It cannot generate cleanup commands.

The assessment must be run on **saved Windows evidence** inside Diaries `change-control/in-progress/0039-DEF - reconcile orphaned Btrfs qgroups on backup/evidence/Step 03/`, with outputs saved under that same defect. It does not prove the snapshots remain unchanged after capture; an entirely separate live safety gate and approved reversible procedure are required before any remediation.
