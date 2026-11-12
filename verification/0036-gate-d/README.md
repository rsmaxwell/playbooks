# 0036 Gate D — unattended acceptance (read-only)

Gate D requires **two distinct, genuinely timer-triggered complete cycles** of `pluto` capture → `mars` guarded pull → eligible `@data` Btrfs snapshot, plus **new off-site replication and receiver receipt**. The 2026-10-16 manual fixed capture/pull/snapshot establishes Gate C only; do not count it for Gate D. A passing shell command, a currently valid marker, or an existing pre-cutover off-site receipt alone does not qualify.

## When to gather evidence

The first scheduled capture is 2026-10-17 00:30 UTC, pull 01:30 UTC, native replication 03:30 UTC. The second scheduled capture/pull is 2026-10-18 00:30/01:30 UTC. Snapshot manager runs hourly and prune at :15. Gather after the second cycle and after verifying an off-site push/receipt whose source snapshot includes a post-cutover fixed dataset. If native push at 03:30 UTC on 17 October only covers the first cycle, capture evidence again after 18 October 03:30 UTC. Do not manually trigger jobs merely to make the acceptance count; investigate failed schedules separately.

Run on `mango` (requires working noninteractive `ssh pluto`, `ssh mars`, `ssh backup`; reading protected Btrfs metadata on the latter hosts may require passwordless `sudo -n`):

```bash
bash verification/0036-gate-d/collect-gate-d.sh "$HOME/0036-gate-d-evidence"
```

The script performs only reads and writes **local evidence files** on `mango`. It deliberately does not start/restart services or modify data, markers, receipts, timer state, retention or snapshots. Read `collection.txt` and resolve any nonzero collection commands; some journal or snapshot reads may need elevated permissions. Do not upload secrets or vault files.

## Decision checklist (all required)

1. **Cycle A and B:** journal demonstrates two independently timer-triggered `diaries-complete-backup-publish.service` successes on 17/18 October (or later separate dates), each with `fixed-capture` (not legacy `publish`); identify **two different backup IDs**, logical dataset `production`, manifest schema 2 and exit status 0.
2. **Matching receiving:** corresponding `diaries-pull.service` successes following each capture, guarded `VERIFIED_FIXED_RECEIVE`, no validation or stale-marker failures, received identity matches each capture. A single current marker contains only the latest identity; journals or prior captured manifests must establish the earlier cycle.
3. **Eligible snapshots:** timestamped Btrfs snapshot manager logs contain `VERIFIED-DIARIES production <backupId>` and `CREATE @data`; verify read-only snapshot contents for each backup ID with `sudo btrfs property get -ts <snapshot> ro` and `sudo python3 /home/richard/scripts/backup/complete-dataset-manifest.py verify --backup-dir <snapshot>/backup/pluto/diaries-backup --allow-fixed-working-root` on `mars`. Snapshot names and manifest IDs must be matched, not inferred from timing alone.
4. **Off-site:** new `btrfs-native-push.service` exit 0; `backup` has matching read-only received subvolume and successful receipt JSON for post-cutover source snapshot. Check source UUID / destination Received UUID / receipt ancestry, and parent protection or full fallback behavior as applicable, by existing 0035 verification guidance. The original 20261016-030037Z receipt alone does not satisfy this requirement.
5. **Safety:** no legacy generation publication used by either timer; no unexpected rollback, stale marker, overlapping writers, failed safety guard, or lost rollback baseline. Do not delete old generations or prune manually for Gate D. Quantitative transfer saving is explicitly not a closure threshold.

Write accepted IDs, UTC timestamps, log ranges, snapshot paths, receipt path and precise conclusion into the Gate D change-control evidence record. If any required evidence is absent, keep Gate D **OPEN**; distinguish a failed operation from incomplete collection.

## Journal collection permissions (16 October correction)

The four service-journal reads now use `sudo -n journalctl --quiet` on
`pluto` and `mars`, because the ordinary SSH account may not have access to
the system journal. This requires **existing, authorised** noninteractive sudo
rights on those hosts. The collector does not change sudoers or grant access.

Check access separately from `mango` before relying on the collection:

```bash
ssh pluto 'sudo -n journalctl --quiet -u diaries-complete-backup-publish.service -n 5 --no-pager'
ssh mars 'sudo -n journalctl --quiet -u diaries-pull.service -n 5 --no-pager'
ssh mars 'sudo -n journalctl --quiet -u btrfs-snapshot-create.service -n 5 --no-pager'
ssh mars 'sudo -n journalctl --quiet -u btrfs-native-push.service -n 5 --no-pager'
```

In `collection.txt`, `status=ENTRIES` means at least one journal line was
collected, `status=EMPTY` means the journal read succeeded but no entries
matched the Gate D UTC window, and `status=ERROR` records a failed journal
query including denied sudo. Before the first scheduled cycle, `EMPTY` is
expected and **does not count as success or failure of an unattended backup**.
Each journal file includes the command output or an explicit empty notice.
Never infer Gate D acceptance from an `rc=0` alone.
