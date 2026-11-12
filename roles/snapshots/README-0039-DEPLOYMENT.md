# 0039-DEF: snapshot-only launcher and host configuration consistency

`./scripts/snapshots.sh mars` and `./scripts/snapshots.sh backup` now run
Ansible in `--check --diff` mode by default and select `--tags snapshots`.
The `snapshots.yaml` entry point uses the **backup-collection** role for `mars`
and the **btrfs-replication** role for `backup`. Each wrapper includes the shared
`snapshots` role with its established, host-specific inputs, rather than
silently reverting to the shared role defaults.

**No direct standalone `snapshots` role installation is intended through this
entry point.** The role remains reusable from the existing host wrappers.

From the **mango SSH terminal**, run these read-only checks after applying:

```bash
cd /home/richard/playbooks
bash -n scripts/snapshots.sh
python3 roles/snapshots/tests/verify-snapshot-launcher-host-context.py
ansible-playbook snapshots.yaml --syntax-check --vault-password-file ~/.vault_pass.txt
./scripts/snapshots.sh mars
```

Inspect all check-mode changes, particularly `/etc/btrfs-snapshot-manager.json`.
On `mars`, the existing verified Diaries marker, dataset path, and writer lock
must be retained. **Do not run `--apply` unless that condition is met.**

Once `mars` is reviewed, check `./scripts/snapshots.sh backup` separately.
This does not authorise deployment to `backup`, snapshot deletion, qgroup
reconciliation, OS upgrades or timer changes.
