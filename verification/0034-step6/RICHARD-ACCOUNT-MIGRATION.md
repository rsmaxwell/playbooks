# 0034 Step 6 — Mars pull execution as `richard`

This is an opt-in correction to the Step 6 verification-only installer. It does not change scheduled jobs or 0035 snapshot timers.

## Motivation

The prior controlled installer placed three helper scripts in `/root/scripts/backup` and ran preflight as root. On mars, `richard` has successfully authenticated to `pluto` via SSH (port 38202) but root has not. The pull should therefore run as `richard`.

## Deployment

From `mango`, in the Playbooks repository:

```sh
ansible-playbook verification/0034-step6/install-and-preflight.yaml --ask-vault-pass
ansible-playbook verification/0034-step6/install-and-preflight.yaml --ask-vault-pass -e step6_install=true
```

The installation creates `/home/richard/scripts/backup` (if necessary), installs `diaries-pull.py`, `complete-dataset-publisher.py` and `complete-dataset-manifest.py` as `richard:richard` with 0755 permissions, and runs the **local** non-mutating preflight as `richard`.

The existing root copies are kept by default. Only after checking the new installation and confirming no other jobs depend on these three paths may you explicitly run:

```sh
ansible-playbook verification/0034-step6/install-and-preflight.yaml --ask-vault-pass -e step6_install=true -e step6_cleanup_legacy_root=true
```

This removes only those three former Step 6 root copies, not the backup directory or any cron/snapshot configuration.

## Read-only connection check on mars

```sh
ssh -o BatchMode=yes richard@pluto hostname
python3 /home/richard/scripts/backup/diaries-pull.py --help
```

Before a real pull, check that the existing mars rsync `--delete` rules cannot delete the receiving tree. Do not execute the pull or change cron until confirmed.

## Caveats

- The prior root-operated local-backup role remains separate and unchanged by this verification playbook. Normal role deployment could still install its own copy depending on its settings; reconcile that integration before production activation.
- This controlled installer does not create a scheduled transfer or run live rsync.
- The `--preflight` check exercises local input validation; successful live SSH and receiving-side publication still need separate verification.
