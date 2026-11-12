# 0040-FEAT Increment 2 — durable peer-transition foundation

Status: IMPLEMENTED IN SOURCE; DISPOSABLE REGRESSIONS PASSED LOCALLY; MANGO VERIFICATION PENDING.

This adds `btrfs-agreed-parent-protocol.py`, an import-only integration primitive for
persisted source and receiver agreed-parent records. It does NOT alter installed
Ansible tasks, timer behaviour, btrfs-native-push.py, receiver endpoints, or pruning.

## Source inspection finding

The current sender (`roles/btrfs-replication/files/btrfs-native-push.py`) still calls
`local('release-source', parent, parent_uuid)` after receiver receipt validation.
That legacy release sequence must not be treated as the new bilateral agreed-parent
protocol. Do not enable new agreed-parent pruning against it.

## Implemented state transitions (only under caller-held endpoint locks)

1. Persist a `pending` candidate independently on both endpoints, after verifying
   the established parent, source snapshot identity, and pins.
2. Independently verify the receiver's durable accepted receipt and both peers'
   pending records; promote to `established`, preserving `previous`.
3. Verify both persisted promotions refer to identical established and previous
   identities; only then acknowledge the previous parent at each endpoint.
4. Any disagreement, missing state, malformed record, or interrupted transition
   requires reconciliation; no implicit state creation, release, or deletion.

**Security boundary:** boolean verification arguments are injectable test/adapter
contracts, not cryptographic attestations and must NEVER be wired directly to a
user-controlled CLI. A production adapter must provide trusted lock-held live
Btrfs checks, receipt identity verification and source-pin protection. Moreover,
state-file persistence alone does not pin a Btrfs subvolume: source and receiver
prune must explicitly honour the union of protected identities before activation.

The module provides no network transport, production CLI, prune authorisation or
independent cross-host durable acknowledgement. This remains the prerequisite
for the later live integration gate.

## Verification on mango

    cd /home/richard/playbooks
    python3 roles/snapshots/tests/verify-0040-agreed-parent-state.py
    python3 roles/snapshots/tests/verify-0040-agreed-parent-protocol.py
    python3 -m py_compile roles/snapshots/files/btrfs-agreed-parent-{state,protocol}.py \
      roles/snapshots/tests/verify-0040-agreed-parent-{state,protocol}.py

Expected: 4 + 7 passing tests, no compilation errors.

## Next gate (not approved for production)

Inspect and implement trusted, lock-held sender/receiver adapter, failure-injection
against actual SSH/Btrfs endpoints on disposable volumes, reconciler, legacy-pin
migration and unified pruning. Then run regressions, Ansible `--check --diff`,
controlled staged deployment, runtime/idempotency checks, and archive evidence.
