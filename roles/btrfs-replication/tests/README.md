> **0042 update (10 November 2026):** The legacy native-push fallback and dormant staged-protocol modules are retired from Playbooks. Only the simplified sender/receiver, shared manager and current regression suites remain operational. Historical tests/guides are preserved via accepted 0040 evidence, 0042 rollback archive and Git history. Older procedures below describe prior 0040 acceptance, not a command to reinstall legacy code.

# 0040-FEAT Step 12 — Simplified agreed-parent replication

## Current status (7 November 2026)

The simplified sender is **installed and active** on `mars`, initiated through
`btrfs-native-push.service` at **03:30 UTC daily**. The corresponding receiver
command is installed on `backup`; receiver scheduling is not enabled there.
The source candidate selector is newest-first, with at most one incremental
transfer from the agreed parent per cycle.

The accepted sequence was: initial common-parent bootstrap and controlled
transfer on 6 November, newest-first controlled transfer to
`20261106-160001Z`, and the first unattended run on 7 November, advancing
the agreed parent to `20261107-030031Z`. Both hosts agreed on the resulting
current and previous parent identities. Do **not** repeat the bootstrap or
live transfer to reproduce these already accepted results.

The simplified retention manager on `backup` has an independently gated
04:15 UTC timer with maximum ten deletions per run. That activation was
authorised and verified on 7 November. Its first unattended run is pending
8 November acceptance. See `../README-0040-SIMPLE-RECEIVER-RETENTION.md`.

## Protocol and protection

- Each host stores a root-owned mode `0600` JSON record containing
  `schema`, `parent` and `prior` with timestamp and source UUID.
- The sender chooses the newest eligible read-only snapshot newer than the
  agreed parent. One cycle transfers at most one; it has no batch option.
- Receiver and sender use the existing snapshot-manager locks. A busy lock
  defers safely rather than introducing a second retry scheduler.
- The receiver advances first. The sender checks the receiver's Btrfs identity
  and state before advancing locally. A lost acknowledgement is reconciled
  without retransmitting a verified completed snapshot.
- An incomplete and provably disposable receiver candidate may be removed
  exactly once during the receive attempt. Ambiguous, held, read-only,
  receipted or otherwise protected candidates are never silently removed.
- Parent/prior pins, checkpoint holds and verified Btrfs snapshot identity
  constrain pruning. Normal journal/service output records results.

## Regression commands on `mango`

Run in `/home/richard/playbooks`. Privileged tests require `sudo -n`, because
they inspect root-owned state and the manager lock. Do not use a standalone
`set -e` in the interactive shell.

```bash
cd /home/richard/playbooks
(
  set -euo pipefail
  sudo -n env PYTHONDONTWRITEBYTECODE=1 python3 roles/btrfs-replication/tests/verify-replication.py
  sudo -n env PYTHONDONTWRITEBYTECODE=1 python3 roles/btrfs-replication/tests/verify-protection.py
  python3 roles/btrfs-replication/tests/verify-shared-retention.py
  python3 roles/snapshots/tests/verify-0040-agreed-parent-prune-guard.py
  python3 roles/snapshots/tests/verify-0040-prune-source-selection.py
  sudo -n env PYTHONDONTWRITEBYTECODE=1 python3 roles/snapshots/tests/verify-0040-simplified-receiver-retention.py
  python3 roles/snapshots/tests/verify-diaries-backup-status.py
  git diff --check
)
rc=$?
if [ "$rc" -eq 0 ]; then echo 'PASS: simplified Btrfs regressions'; else echo "FAIL: regressions (exit $rc)"; fi
```

The permanent agreed-parent protection regression now also checks that all
three source/receiver pruning planners consult the protected agreed-parent
pins. The cutover-readiness and legacy-source-retirement tests were one-off
migration checks and have been retired from Playbooks. Their original scripts
and accepted passing results are preserved under 0044-FEAT change-control
and in Playbooks Git history. The normal protocol, protection and retention
regressions remain maintained here.

The disposable real-Btrfs sender/receiver retention acceptance scripts and
historical execution evidence belong to the Diaries `0040-FEAT` change-control
directory. The 146 superseded test/guide files were archived there and
retired from Playbooks as a separate accepted cleanup.

## Operations and rollback

- Read the real sender and receiver parent records before any emergency
  source/receiver recovery decision.
- Confirm the source timer still runs at 03:30 UTC and uses the simplified
  executable. The legacy service *name* does not imply the legacy executable.
- Receiver pruning is authorised only under the existing retention policy,
  daily 04:15 UTC and maximum ten deletions per run.
- Do not start extra live replication, reset the agreed parent, remove holds,
  clear a pending prune journal or switch to the legacy binary casually.
- A rollback to legacy transport requires explicit review of incompatible
  state/receipt semantics, not a direct `ExecStart` change.

## New read-only status regression (prepared after 7 November acceptance)

`verify-replication.py` also checks `sender status`: verified
source and receiver Btrfs identities, incremental and receiver-ahead plans,
and no call to `save_state` or `stream_send`. Both `sender status` and
`receiver status` refuse to create an absent manager lock file. The
`verify-diaries-backup-status.py` regression checks that the operational
report uses only the simplified `sender status` contract, preserves the
previous report sections and refuses invalid/unverified receiver state.
The current source package does **not** certify live deployment or the first
8 November unattended receiver-prune result.
