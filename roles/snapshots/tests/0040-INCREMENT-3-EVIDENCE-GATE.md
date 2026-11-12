# 0040-FEAT — Increment 3A: Btrfs evidence validation foundation

Status: IMPLEMENTED, local tests passed; mango verification PENDING. No production changes.

This increment inspects the actual source schema in `roles/btrfs-replication/files/btrfs-native-push.py`, `btrfs-native-push-receiver.py`, and `btrfs-native-endpoint.py`. The existing endpoint supports `inspect-source`/`inspect-receiver`, and receiver receipt checks source/receiver UUID, filesystem IDs, transport, send/receive return codes, and readonly status.

Added `roles/snapshots/files/btrfs-agreed-parent-evidence.py`: a pure read-only validator accepting captured endpoint metadata and receiver receipt, plus fail-closed union of the two endpoints' protection states. This is NOT a live capture, lock-held protocol, replication integration, deployment, approval or permission to prune. An observation can become stale as soon as the endpoint locks are released. All actual pinning and receiver-prune authorisation remain unchanged.

Local regression execution: 7 evidence checks, 4 state checks, 7 protocol checks passed. `py_compile` should also succeed.

Next design gate: implement a constrained network evidence collector using the installed allowlisted endpoint and receiver interfaces. The receiver receipt must be collected under its writer lock, without creating an unconstrained SSH command or trusting unverified JSON. Hold locks and pin both the established and candidate snapshots across all protocol state writes. Establish two-host durable acknowledgement and interruption recovery before replacing the existing post-acceptance `release-source` path. Preserve previous parent until verified on both endpoints. Add disposal-only interrupted-transfer tests. Source integration must be followed by `--check --diff`, approved rollout, runtime evidence and idempotency checks.

On mango:

```bash
cd /home/richard/playbooks
python3 roles/snapshots/tests/verify-0040-agreed-parent-state.py
python3 roles/snapshots/tests/verify-0040-agreed-parent-protocol.py
python3 roles/snapshots/tests/verify-0040-agreed-parent-evidence.py
python3 -m py_compile roles/snapshots/files/btrfs-agreed-parent-{state,protocol,evidence}.py roles/snapshots/tests/verify-0040-agreed-parent-{state,protocol,evidence}.py
```
