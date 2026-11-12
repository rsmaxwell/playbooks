# 0035 Step 4 — History locator, `mars` and `pluto`

Run the source regression first:

```bash
python3 roles/snapshots/tests/verify-diaries-backup-history.py
```

Existing `mars` tool (already deployed) uses its snapshot-manager configuration:

```bash
ansible mars -b -m command -a '/usr/local/sbin/diaries-backup-history list --all'
```

To install only the history locator and independent manifest verifier on `pluto`, without touching its ext4 filesystem or Btrfs timers:

```bash
ansible-playbook verification/0035-step4/install-pluto-history.yaml --ask-vault-pass --check --diff
ansible-playbook verification/0035-step4/install-pluto-history.yaml --ask-vault-pass
```

On `pluto`:

```bash
/usr/local/sbin/diaries-backup-history --published-root /home/richard/projects/diaries/data/diaries-backup list
/usr/local/sbin/diaries-backup-history --published-root /home/richard/projects/diaries/data/diaries-backup list --all
/usr/local/sbin/diaries-backup-history --published-root /home/richard/projects/diaries/data/diaries-backup --manifest-tool /usr/local/lib/diaries-backup/complete-dataset-manifest.py verify BACKUP_ID
```

`pluto` is ext4: `live` means fixed published backup, **not** a Btrfs snapshot. This tool only locates; it never restores or prunes. The `mars` mode still requires matching verification markers. No receiver/backup deployment is included in Step 4.
