#!/usr/bin/env python3
"""Read-only 0048 preflight: checkout modes and backup-collection task policy.

These are the accepted checkout modes at umask 022, not a Git-guaranteed mode
contract. Check the actual source tree before deploying archive-mode rsync.
"""
from pathlib import Path
import stat
import sys
import yaml

role = Path(__file__).resolve().parents[1]
source_dirs = (
    "files/backup", "files/backup/home", "files/backup-machine",
    "files/backup-machine/home", "files/backup-machine/remote",
)
filters = tuple(
    f"files/{branch}/{name}"
    for branch in ("backup/home", "backup-machine/home", "backup-machine/remote")
    for name in ("includes", "excludes-1", "excludes-2")
)
errors = []
for relative in source_dirs + filters:
    path = role / relative
    is_directory = relative in source_dirs
    if path.is_symlink() or not path.exists() or path.is_dir() != is_directory:
        errors.append(f"{relative}: missing, symlink or incorrect type")
        continue
    expected = 0o755 if is_directory else 0o644
    actual = stat.S_IMODE(path.stat().st_mode)
    if actual != expected:
        errors.append(f"{relative}: mode {actual:04o}, expected {expected:04o}")

for task_name, source in (
    ("install_user_scripts.yaml", "backup/"),
    ("install_machine_scripts.yaml", "backup-machine/"),
):
    try:
        tasks = yaml.safe_load((role / "tasks" / task_name).read_text())
        creates = [t for t in tasks if t.get("name", "").endswith("Create directories")]
        copies = [t["ansible.posix.synchronize"] for t in tasks if "ansible.posix.synchronize" in t]
        assert len(creates) == len(copies) == 1
        sync = copies[0]
        assert sync.get("archive") is True and sync["src"] == source
        opts = sync["rsync_opts"]
        assert "--omit-dir-times" in opts
        assert not any("--chmod" in x or "--no-perms" in x for x in opts)
        file_task = creates[0]["ansible.builtin.file"]
        assert file_task["state"] == "directory"
        if source == "backup/":
            assert file_task["path"] == "{{ backup_directory.path }}"
            assert file_task.get("mode") == "{{ backup_directory.mode | default(omit) }}"
            assert {x["path"]: x.get("mode") for x in creates[0]["loop"]} == {
                "{{ normal_user_home }}/scripts/backup": None,
                "{{ normal_user_home }}/scripts/backup/home": None,
                "{{ normal_user_home }}/scripts/backup/cron": "0750",
                "{{ normal_user_home }}/log/backup": "0750",
            }
        else:
            assert file_task["path"] == "{{ backup_directory }}"
            assert "mode" not in file_task
            assert set(creates[0]["loop"]) == {
                "/root/scripts/backup", "/root/scripts/backup/cron",
                "/root/scripts/backup/home", "/root/scripts/backup/remote",
                "/root/log/backup",
            }
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        errors.append(f"{task_name}: unexpected Ansible policy: {exc}")

if errors:
    for issue in errors:
        print("FAIL:", issue, file=sys.stderr)
    raise SystemExit(1)
print("PASS: five Git-native source directories 0755, nine filters 0644; "
      "no conflicting directory mode or rsync override")
