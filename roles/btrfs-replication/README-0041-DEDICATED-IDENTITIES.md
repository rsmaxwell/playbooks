# 0041-FEAT — Dedicated replication identities and canonical service

The dedicated identities, forced receiver command and restricted sender gate were
provisioned and verified in Steps 7–10. The first supervised production
incremental transfer via `btrfs-send` and `btrfs-receive` passed on 15 November
2026. Step 11 makes the canonical `btrfs-native-push.service` use the dedicated
sender account **when the scheduling Ansible role is explicitly deployed**.
Simply applying the source ZIP does not modify the installed systemd unit.
The existing `btrfs-native-push.timer` remains at 03:30 UTC and is not renamed.

## Boundaries

* `mars`: non-admin, no-login `btrfs-send` account and private Ed25519 SSH key,
  generated **only on mars**. The pinned receiver host key lives under a
  root-controlled `/etc/btrfs-replication-0041/known_hosts`; `-F /dev/null`
  disables service-user SSH client configuration. A single fixed `sudo` command executes the
  root-owned sender transaction. The existing replication code retains the
  snapshot-manager flock across sending, receiver acknowledgement/readback and
  parent advancement. Its SSH subprocess is **always** run as `btrfs-send` in
  `BTRFS_REPLICATION_IDENTITY_MODE=dedicated`; it does not fall back to `richard`.
* `backup`: non-admin `btrfs-receive` account with a password-locked login and
  root-managed `authorized_keys` containing exactly one forced-command,
  `restrict` entry. The account uses `/bin/sh` solely because OpenSSH forced
  commands require a usable login shell. Its home and `.ssh` directory are
  **root-owned 0755**; the authorized key file is **root-owned 0644**, not
  writable by the service user. The root gate reads and validates one bounded
  JSON request header from stdin, then directly execs the existing root-owned
  receiver runtime, leaving the binary stream at its exact first byte.
* Both service-only sudoers rules allow one fixed executable **with no
  arguments**. Unknown SSH operations, shell/PTY/forwarding and `bootstrap`
  are not allowed via the service key. The receiver's existing Btrfs identity,
  checkpoint-hold, state and lock checks remain authoritative.
* Existing `richard` SSH/sudo accounts and legacy service transport are not
  changed or removed. Existing snapshot creation/pruning, stale-qgroup
  cleaning and root-owned agreed-parent records are unchanged.

## Source-only verification

From `mango` in `/home/richard/ansible-controller/playbooks`:

```bash
python3 roles/btrfs-replication/tests/verify-0041-restricted-identity.py
python3 roles/btrfs-replication/tests/verify-replication.py
```

The additive Ansible tasks are imported from `tasks/native.yaml` but require
**both** the dedicated tag and a non-default opt-in variable:

```bash
# Read-only, partial first-run preview; never generates the key in check mode.
ansible-playbook btrfs-replication.yaml --check --diff \
  --limit 'mars,backup' --tags btrfs-0041-provision \
  -e btrfs_0041_additive_enabled=true \
  --vault-password-file ~/.vault_pass.txt
```

On a virgin host, Ansible check mode cannot obtain the key that must only be
generated on `mars`. Such dependent tasks are skipped in check mode by design.
This is **not** a complete proof of the eventual file contents or SSH access.
The full additive deployment must remain a separately reviewed action.

## Recorded pre-cutover safeguards (Steps 7–10 passed)

1. Review source and sudoers scope; confirm inventory groups and endpoint roles.
2. Verify receiver SSH host-key fingerprint for port 39263 against the server's
   actual ED25519 public key; never accept unknown keys automatically.
3. Run syntax/regression and partial check mode on mango; review exact changes.
4. Authorise additive account/key provisioning on both hosts, then verify live
   `sshd`, forced-command rejection tests, sudo restrictions and idempotence.
5. Perform isolated/disposable binary Btrfs send/receive and interruption tests
   (including stream integrity, manager lock contention and protected parents).
6. Review receiver `.replication-state` ownership and its `writer.lock` before
   any root-ownership migration; do **not** replace active lock inodes.
7. Step 11: the canonical service transition is controlled by
   `btrfs_native_sender_service_identity` (`dedicated` in the accepted source;
   `legacy` for rollback) with a narrowly scoped scheduling Ansible run.
   The 03:30 timer, retained parent files, personal `richard` account and
   other root maintenance services must remain unchanged. Do not rewrite
   agreed-parent JSON during rollback.
8. After cutover, accept one timer-triggered 03:30 run with verified receiver
   UUID, agreed parent, backup health and root-owned state permissions before
   closing 0041.

**Security limitation:** The fixed sender privilege gate still executes the
existing root-owned transaction implementation. This narrows the callable
operations and separates SSH credentials, but does **not** reduce the amount
of established trusted Python transaction logic running with root privileges.
Further internal privilege separation should be assessed only if supported by
an equivalent uninterrupted-lock / recovery integration test.
