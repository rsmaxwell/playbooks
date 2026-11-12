# 0035 Step 8 — Retention, restore and failure acceptance

## Gate A: safe observation (read-only)

```bash
cd ~/playbooks
python3 verification/0035-step8/verify-source-contract.py
set -o pipefail
ansible-playbook verification/0035-step8/verify-acceptance.yaml --ask-vault-pass | tee /tmp/0035-step8-acceptance.txt
```

No snapshot creation, deletion, receive, timer changes, or restore occurs. The playbook checks protected read-only sets, accepted receipt chain, history visibility, legacy mirror and receiver passivity. **Gate A alone cannot close Step 8.**

## Gate B: acceptance evidence reconciliation

Use previously recorded 0034 evidence where it establishes a scenario. Document each evidence filename/command, date, expected and observed result. Required by the 0035 implementation plan: GFS boundary and newest-set retention; active parent/candidate pinning; real absolute restore paths; schema-2 restoration into a disposable environment; storage pressure; SSH loss; interrupted full and incremental stream; duplicate receive; stale/unknown parent; and usable previous accepted receive. Preserve UUID/path evidence.

Never simulate storage pressure or transport failures on the live production pipeline. Use a disposable Btrfs test environment and a disposable restore target. Existing checks do **not** prove interruption handling or transfer-size measurements unless those logs are actually supplied.

**Leave Step 8 OPEN until evidence is reconciled and accepted.**
