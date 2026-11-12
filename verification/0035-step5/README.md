# 0035 Step 5 — Guarded timestamp cleanup

Step 5 is installed but **not closed** until on-host evidence is reviewed. Existing `mars` GFS settings are not changed. `pluto` remains ext4 and will report UNSUPPORTED/no-op. No Snapper numeric snapshots, received snapshots, or conventional backup directories are touched.

From `mango`:

```bash
cd ~/playbooks
python3 verification/0035-step5/verify-source-contract.py
ansible-playbook verification/0035-step5/install-cleanup.yaml --ask-vault-pass --check --diff
ansible-playbook verification/0035-step5/install-cleanup.yaml --ask-vault-pass
ansible mars -b -m command -a '/usr/local/sbin/diaries-snapshot-cleanup --host mars dry-run'
ansible pluto -b -m command -a '/usr/local/sbin/diaries-snapshot-cleanup --host pluto dry-run'
```

**Do not run `--apply prune` as Step 5 acceptance.** The existing `mars` prune timer is already active; this installation does not adjust it. Live destructive pruning is a separately authorised operation. The wrapper's `prune --apply` delegates to the protected existing manager; requires root privileges and validates every candidate before touching any root/@data pair. Save transcripts before documenting closure.

Unsupported or unsafe states fail closed. In particular, incomplete timestamp sets block pruning; active/replication pins and checkpoint holds are retained by the manager. The tool never discovers numeric Snapper IDs as timestamp snapshots.
