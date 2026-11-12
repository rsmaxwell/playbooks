# 0040-FEAT — Increment 1: agreed-parent state primitive

Status: SOURCE IMPLEMENTED / DISPOSABLE REGRESSIONS PASS / NOT DEPLOYED.

New files:
- `roles/snapshots/files/btrfs-agreed-parent-state.py`
- `roles/snapshots/tests/verify-0040-agreed-parent-state.py`

Contract: schema 1, established/pending/previous snapshots with timestamp and UUID.
`prepare()` pins new candidate beside established parent. `promote()` moves
pending to established while retaining previous. `acknowledge_previous()`
releases previous only when caller has independent bilateral durable confirmation.
The module does not supply that bilateral protocol; do not wire any release
operation to replication without implementing and testing it.

Atomic write uses temporary file, fsync, replace, directory fsync; an external
exclusive lock is REQUIRED around read/modify/write transactions. Missing,
corrupt or unsafe state fails closed on read. This component is deliberately
dormant and must not be deployed by Ansible in this increment.

Local disposable evidence (2026-10-30):
`python3 roles/snapshots/tests/verify-0040-agreed-parent-state.py`
4 tests passed; `python3 -m py_compile` passed.

Next gate: apply via Beyond Compare, rerun on mango; review source and
regression output before implementing replication integration. No Ansible
`--check --diff` or production deployment is warranted for these dormant files.
