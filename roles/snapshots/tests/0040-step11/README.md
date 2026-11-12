# 0040-FEAT Step 11 — one-time checkpoint-hold preview

**Status: preview-only source implementation. No commit, configuration change, or snapshot deletion is authorised.**

The current production snapshot manager requires checkpoint hold `source_uuids` to match the complete configured source set exactly. The two historical holds currently use `root` and `@data`; the eventual final config uses only `@data`. This standalone preview validates **both** historical UUIDs and displays the future schema-1 hold records. It intentionally contains no write or deletion code.

Run offline regression in the **mango SSH terminal**:

```bash
cd /home/richard/playbooks
python3 roles/snapshots/tests/0040-step11/verify-preview.py
```

For production read-only preview from **mango**, stream the reviewed tool directly over SSH rather than copying it to `/tmp` on mars:

```bash
cd /home/richard/playbooks
ssh mars 'sudo python3 -' < roles/snapshots/tests/0040-step11/preview-checkpoint-hold-migration.py
```

Expected: `PREVIEW ONLY`, both holds, correct `@data` UUIDs, `PASS`. If there is any unexpected state, the utility refuses without writing. Preview is NOT approval to migrate or retire root snapshots.

The eventual cutover must coordinate an atomic hold-file replacement with an Ansible configuration change, preserve rollback evidence, prevent concurrent snapshot-manager operations during the incompatible intermediate state, and perform hold verification before allowing pruning. A separately reviewed one-time commit utility/runbook must be produced for that gate; do not edit the hold JSON manually.

The source bundle dated 2026-10-25 16:01 predates the deployed per-source source changes. This tool is deliberately independent of snapshot-manager internals and does not overwrite the installed manager.
