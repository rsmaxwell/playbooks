# Btrfs snapshot replication and backup management (0049)

Current operational scheme: **agreed-parent Btrfs replication**, with one sender
(`mars`) and one receiver (`backup`). There is no second replication scheme.
Btrfs send/receive, protected parent/prior identities, receiver deletion gates,
checkpoint holds, and the 0041 dedicated `btrfs-send`/`btrfs-receive` access
controls are unchanged by 0049.

## Operator commands

| Command | Host | Behaviour |
| --- | --- | --- |
| `sudo -n btrfs-backup-status` | both | Read-only infrastructure status |
| `sudo -n btrfs-backup-status --local-only` | both | Local-only report, no SSH |
| `sudo -n btrfs-backup-status --json` | both | Pretty-printed JSON report |
| `sudo -n diaries-backup-status` | mars | Retained Diaries datasets only |
| `sudo -n diaries-backup-status --limit 20 --json` | mars | JSON dataset summary |
| `sudo -n diaries-backup-history list` | mars | Full grouped dataset history |
| `sudo -n btrfs-snapshot-manager list` | both | Snapshot inventory table |
| `sudo -n btrfs-snapshot-manager prune --dry-run` | both | Endpoint-aware read-only retention preview |
| `sudo -n btrfs-snapshot-manager prune --max-delete N` | both | Destructive bounded prune; guarded |
| `sudo -n env BTRFS_REPLICATION_IDENTITY_MODE=dedicated btrfs-replication sender status` | mars | Full read-only preflight over the 0041 dedicated transport |
| `sudo -n btrfs-replication receiver status` | backup | Receiver local protocol state (compact on wire) |

Always trigger live collection/replication through the existing restricted
systemd service boundary, **not** `btrfs-replication sender cycle` as an
ordinary operator:

- `diaries-pull.service` on `mars` (unchanged)
- `btrfs-push.service` on `mars` (renamed; executes fixed 0041 wrapper as `btrfs-send`)
- `btrfs-receiver-prune.service` on `backup` (renamed; bounded guarded prune)

Timers remain at their existing inventory-selected schedules; **do not infer**
effective values from role defaults. `btrfs-backup-status` distinguishes a
verified publication marker, a successful systemd run, the locally recorded
agreed parent, and a verified remote parent; it does **not** claim that a parent
record is independent proof of the time of a last transfer. A service result
without an exit timestamp is not a last successful run.

JSON schema for both status programs: `schema=1`, `health=healthy|degraded|error`;
exit codes `0` (healthy), `1` (degraded), `2` (required report unavailable).
Tables are titled, headered and dynamically sized; JSON is two-space indented.
The receiver protocol replies stay compact to preserve existing SSH/stream
handling. The `--local-only` mode never invokes the sender's SSH preflight.

On `mars`, the full `btrfs-backup-status` automatically selects the dedicated
0041 SSH transport for its read-only sender check. The raw replication CLI
needs the explicit environment assignment shown above; an unset transport
mode retains a historical route and must not be used for normal diagnostics.

## Safe deployment: same working replication protocol

The 0049 naming transition changes **operator names and installation wiring**;
it does not change the send/receive implementation. Deploy `backup` **before**
`mars` to allow an old sender to continue speaking to the new receiver gate
while source migration is pending. Both ends must be on the reviewed current
0041 code before this transition.

The Playbooks task order installs the new runtime and both fixed gates first,
then checks that the corresponding old service is not active, disables the old
timer, enables the replacement, removes old unit files and `/usr/local/bin/
btrfs-simplified-replication`. It never changes the 0041 SSH key, forced-command
or sudoers authority. **Do not deploy during an active source push or receiver
prune**, and inspect the result of Ansible check mode before changing services.
There must be exactly one active timer for push and receiver pruning after
cutover. Expected examples: `btrfs-push.timer`, `btrfs-receiver-prune.timer`.

Old `.simple-agreed-parent.json` and `.simple-prune-pending.json` **remain
unchanged as persistent internal file paths**. Their identities, permissions,
contents and protection are not reset by 0049. Historic role tests, 0040/0041
reports and rollback records retain historically correct names. Internal
Python `receiver_simple_*` helper functions remain solely to preserve the
verified implementation; they are no longer published as operator commands.

The private inventory was intentionally excluded from the upload bundle.
New vars (`btrfs_push_*`, `btrfs_replication_*`, `btrfs_receiver_*`) fall back
to the old inventory names to prevent accidentally disabling live schedules
at initial deployment. After checking effective inventory, migrate its old
keys in the private `inventory` repository and remove the fallbacks in a
separately verified follow-up. Do not set new names to false while old names
still contain the approved true production settings.

See Diaries parent feature `change-control/in-progress/0049-FEAT - rationalise
Btrfs and Diaries backup management/` for tests, rollout/rollback and evidence.
