# 0040-FEAT Step 11 — Historical root snapshot retirement

This package is **preparation only**. It does not authorise deleting the 63 historical root snapshots.

## Evidence and scope

- Fixed manifest: `root-retirement-manifest.json`, constructed from accepted `2026-10-26 08:04` read-only inventory.
- Exactly 63 timestamped subvolumes beneath `/media/usb/@snapshots/root`, with identities and UUIDs.
- Snapshot manager is `@data` only, using the production `sources` schema: one entry with `path=/media/usb/@data` and boolean `required=true`, `creation=true`, `prune=true`. The source endpoint uses `/media/usb/@snapshots/@data`.
- Two historical `@data` checkpoint holds must exist with matching UUIDs.
- Replication-protected `@data` snapshots must exist with matching UUIDs.
- The manager lock must be free; native push service must be inactive.
- Every root snapshot must be read-only and match its subvolume ID and UUID.
- Every entry in the root directory must appear in the manifest; nested root subvolumes are refused.

## Test and preview — no production mutations

**mango SSH terminal** after comparing/applying this package to `/home/richard/playbooks`:

```bash
cd /home/richard/playbooks
python3 roles/snapshots/tests/0040-step11/verify-retirement.py
python3 -m py_compile roles/snapshots/tests/0040-step11/retire-historical-root.py
```

**mango SSH terminal**: stream code to mars without leaving temporary executables. Stream the fixed manifest separately to a read-only evidence destination only after reviewing the path and permissions; the script assumes it lives beside itself, so the recommended preview execution is via a *read-only remote extraction* from this package into an appropriately restricted working directory, not an ad hoc script copied under `/tmp`.

To avoid staging or installing any program on mars, a preview can instead stream an in-memory ZIP of exactly these two files and invoke it through `python3 -`; that deployment method is deliberately **not** embedded in this runbook pending verification of the production environment. The current package implements the planner and offline tests. Its executable production preview is the next separate acceptance gate.

## Irreversible commit — NOT AUTHORISED

The program supports a locked, fixed-manifest commit requiring an explicit authorisation token. It creates a root-owned receipt and fsyncs each deletion result. It fails closed if a receipt already exists (including a partial run), requiring human reconciliation rather than automatic resumption. Btrfs subvolume deletion cannot be rolled back simply by reversing Ansible configuration.

**Do not run `--commit` until the preview and independently preserved recovery material have been reviewed and deletion has been explicitly authorised.**

The source/receiver schedules, retention, replication state and historical checkpoint protection must not be altered to accommodate this retirement.

## 2026-10-26 preview correction

The initial production preview correctly refused because an obsolete planner assertion expected non-existent top-level `required_snapshot_sources` and `creation_source_names` keys. This revision checks the deployed per-source booleans instead and includes positive and negative offline tests. No root deletions were performed. Re-run the read-only preview; irreversible commit is still not authorised.

## 2026-10-26 filesystem-relative listing correction

The second production preview refused `Btrfs root candidate mismatch (0 vs 63)` because the planner queried the nested snapshot directory. The installed Btrfs tooling reports the expected root paths when queried from `/media/usb`. The planner now lists from that filesystem mount and filters exact `@snapshots/root/` paths, ignoring sibling `@data` entries while refusing any nested root subvolumes. An offline fixture reproduces the observed mixed listing. **No deletion is authorised.**

## Commit hardening review (2026-10-26) — NOT AUTHORISED

The accepted production read-only preview validated all 63 exact identities. This revision:

- Writes and fsyncs `BEGIN` (including SHA256 of manifest) and `DELETE_INTENT` **before** each Btrfs delete, and `DELETED` afterwards; `COMPLETE` only after all 63 return successfully.
- Atomically creates the root-owned receipt with `O_EXCL` and fsyncs its parent directory before issuing any Btrfs deletion. A pre-existing receipt (including an incomplete one) blocks every future commit. Ambiguous intent requires manual reconciliation and explicit new change control, not replay.
- Rechecks protected `@data` checkpoint holds, replication pins, endpoint and source configuration, and the candidate identity before each deletion. Holds the snapshot-manager flock for the full operation.
- Requires the **native push service** to be masked in systemd and inactive before any deletion, and rechecks it before each deletion. The planner does **not** mask/unmask units or stop/start timers; these are separate, explicitly approved production maintenance actions. The runtime mask ensures a push cannot start via its timer or manually. Any scheduled push attempts during a mask would fail, so the eventual cutover requires a reviewed short maintenance window and prompt rollback of that mask afterward.
- Offline tests verify journal ordering, an injected Btrfs failure leaving `DELETE_INTENT` with no false success, and rejection of unmasked native push service. No actual deletion is performed by tests.

Outstanding before permission to delete: independently preserved recovery/evidence review; a full controlled test of the commit control path on disposable Btrfs subvolumes or equivalently strong mock tests; a live **read-only** re-preview after applying this revision; explicitly approved replication isolation/restoration steps and verification of the offsite recovery state; explicit final authorisation. Do not run `--commit` now.

**Note on durability:** `btrfs subvolume delete` may complete namespace removal before all asynchronous filesystem cleanup. Fsyncing the receipt records the command outcome, not proof that disk-space reclamation finished. An incomplete receipt is an uncertain state; do not retry automatically.
