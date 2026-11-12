# 0036 Gate E — controlled six-generation retirement

This is **Stage 1 only**. The six non-alias-target generation directories are moved to a same-filesystem hold (`.diaries-backup-generations/.0036-retirement-hold/`); they are **not deleted**, so the operation is reversible. The two `20261016-003019Z` rollback targets and both `pre-0036-rollback` symlinks are NEVER touched. Off-site snapshots, Snapper snapshots, timers and backup scripts are NEVER modified.

Execute on **mango** from `~/playbooks`:

```bash
python3 -m py_compile verification/0036-gate-e/retire-nonalias-generations.py
python3 verification/0036-gate-e/retire-nonalias-generations.py --mode plan | tee ~/0036-gate-e-retirement-plan.txt
```

Review and upload the plan first. If the plan is satisfactory, the specifically approved reversible move is:

```bash
python3 verification/0036-gate-e/retire-nonalias-generations.py --mode quarantine --confirm 0036-GATE-E-SIX-NONALIAS-ONLY | tee ~/0036-gate-e-retirement-apply.txt
python3 verification/0036-gate-e/retire-nonalias-generations.py --mode plan | tee ~/0036-gate-e-retirement-postcheck.txt
```

To undo the retirement (requires same preconditions):

```bash
python3 verification/0036-gate-e/retire-nonalias-generations.py --mode restore --confirm 0036-GATE-E-SIX-NONALIAS-ONLY
```

The tool refuses operation if a manifest SHA differs from the v3 accepted evidence, if an alias or active fixed path differs, or if the associated one-shot service is not inactive or the timer is not enabled and active. It never uses `sudo`, and aborts upon the first host failure. Note cross-host transactions are not atomic: if `pluto` succeeds but `mars` fails, inspect and rerun or restore.

**No permanent deletion is implemented or authorised here.** No rollback-target removal or Gate E closure is implied. Take care: `mv`/rename preserves data and consumes no appreciable less disk space. This stage primarily retires operational namespace entries while retaining recoverability. A future irreversible deletion needs separate approval and a fresh snapshot-retention check.
