# 0040-FEAT Increment 3G — Bootstrap candidate (source verification gate)

Candidate: `20261030-030033Z`, source UUID `d901ddd2-66c7-0b42-b26c-ab6886273b7a`.

This ZIP adds source-only tooling: no Ansible task, sudoers, live endpoint, schedule or pruning changes.
The CLI is **plan-only**; the commit helper is **disposable tests only**. No production state creation is authorised.

Live evidence observed 2026-10-30: matching sender UUID and receiver Received UUID, read-only snapshots, matching receipt and source protection pins; receiver prune disabled. Both agreed-parent state files are absent.

Critical blocker: current `btrfs-native-push.py` still contains `release-source` after receipt confirmation. Until it is replaced or coordinated with a durable pin-and-state migration, the selected parent could become unprotected on a future transfer. Also source pruning and writer operations must be isolated during bootstrap, with stable lock order and interruption recovery designed before applying a live state write.

## Test on mango

`python3 roles/snapshots/tests/verify-0040-agreed-parent-bootstrap.py`

`python3 roles/snapshots/files/btrfs-agreed-parent-bootstrap.py --plan`

The disposable test checks identity and pins, refuses active receiver pruning, requires caller-asserted lock and scheduler isolation, rejects corrupted state, and demonstrates identical-state idempotency. Boolean assertions are test contracts, not a substitute for actual production lock/scheduler enforcement.

Next gate: review source tests and obtain live lock/schedule configuration evidence, then implement Ansible-managed guarded bootstrap with check/diff before any production state write.
