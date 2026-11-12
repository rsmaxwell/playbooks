# 0034-FEAT Step 6 — controlled helper deployment and preflight

This playbook is deliberately separate from `local-backup.yaml` and `diaries.yaml`. In particular, it never includes the `snapshots` role: the recovered 0035 role can enable timers and change Snapper scheduling.

## Prerequisites

Apply the already supplied Step 5 and Step 6 source overlays to Playbooks. Ensure `roles/diaries/files/sync/scripts/complete-dataset-publisher.py`, `roles/diaries/files/sync/scripts/complete-dataset-manifest.py`, and `roles/local-backup/files/backup-machine/diaries-pull.py` are present. Ansible inventory must resolve `pluto` and `mars`.

## Run from Playbooks root on mango

Read-only inspection (default, no changes):

```bash
ansible-playbook -i <YOUR_INVENTORY> verification/0034-step6/install-and-preflight.yaml
```

Only after reviewing the inspection result, opt into installing the helpers and running non-mutating preflights:

```bash
ansible-playbook -i <YOUR_INVENTORY> verification/0034-step6/install-and-preflight.yaml -e step6_install=true
```

Do not replace `<YOUR_INVENTORY>` with a guessed path; if Ansible already has a default inventory configured, omit `-i <YOUR_INVENTORY>`.

The installation creates the destination parent if missing; no backup content is pulled, promoted or snapshotted. No cron or systemd state is changed. Existing 02:00/02:15 Mars backups remain unchanged.

## Additional read-only checks before any actual transfer

- On `pluto`, run `python3 ~/projects/diaries/scripts/complete-dataset-publisher.py --published-root ~/projects/diaries/data/dataset-backups/production/diaries-backup verify-current`. It will fail if the production publisher has not yet published a valid generation; **do not run a real pull in that case**.
- On `mars`, as the user that will run the pull (currently helper install is root-owned), verify `ssh -o BatchMode=yes pluto true` and `ssh -o BatchMode=yes pluto 'command -v flock; command -v rsync'`. SSH alias and host-key trust are not established by the provided inventories.
- Inspect existing include/exclude lists and scheduled rsync paths to ensure `/media/usb/@data/backup/pluto` will not be deleted or altered by existing jobs.
- Confirm whether remote source `pluto` SSH identity differs for root and `richard`; this pilot does not change SSH keys or authentication.

## Status

This is installation/preflight only; no live pull is executed. Step 6 remains open pending verified production publication, SSH identity check, first deliberate transfer, receiving-side validation, and replication acceptance evidence.
