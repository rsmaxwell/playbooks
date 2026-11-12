#!/usr/bin/python3

from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import yaml

ROLE = Path(__file__).resolve().parents[1]
MANAGER = ROLE / "files" / "btrfs-snapshot-manager.py"
HISTORY = ROLE / "files" / "diaries-backup-history.py"
EXTENT_TOOL = ROLE / "files" / "btrfs-extent-sharing.py"
TASKS = ROLE / "tasks" / "main.yaml"
DEFAULTS = ROLE / "defaults" / "main.yaml"
README = ROLE / "README.md"
PLAYBOOK_ROOT = ROLE.parents[1]
COLLECTION = PLAYBOOK_ROOT / "roles" / "backup-collection" / "tasks" / "main.yaml"
REMOTE_BACKUP = PLAYBOOK_ROOT / "roles" / "btrfs-replication" / "tasks" / "main.yaml"
SNAPSHOT_PLAYBOOK = PLAYBOOK_ROOT / "snapshots.yaml"
SNAPSHOT_SCRIPT = PLAYBOOK_ROOT / "scripts" / "snapshots.sh"

spec = importlib.util.spec_from_file_location("btrfs_snapshot_manager", MANAGER)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS: {message}")


def fake_snapshots(now: datetime, hours: int):
    values = []
    for offset in range(hours):
        dt = now - timedelta(hours=offset)
        name = dt.strftime(module.TIMESTAMP_FORMAT)
        values.append((name, dt, Path("/fake") / name))
    values.sort(key=lambda row: row[1], reverse=True)
    return values


now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
policy = module.RetentionPolicy(hourly=4, daily=3, weekly=2, monthly=2, yearly=2, minimum_age_minutes=30)
snapshots = fake_snapshots(now, 24 * 80)
keep = module.retention_keep_set(snapshots, policy, now)

check(snapshots[0][0] in keep, "retention always keeps newest snapshot")
check(len({module.bucket_hour(dt) for name, dt, _ in snapshots if name in keep}) >= 4,
      "retention keeps configured recent hourly buckets")
check(len({module.bucket_day(dt) for name, dt, _ in snapshots if name in keep}) >= 3,
      "retention keeps configured daily buckets")
check(len({module.bucket_week(dt) for name, dt, _ in snapshots if name in keep}) >= 2,
      "retention keeps configured weekly buckets")
check(len(keep) < len(snapshots), "retention thins older snapshots")

try:
    module.parse_timestamp("381")
except ValueError:
    pass
else:
    raise AssertionError("numeric Snapper IDs must not parse as managed timestamps")
print("PASS: numeric Snapper IDs are outside the managed timestamp namespace")
check(module.parse_timestamp("20261008-070000Z").tzinfo == timezone.utc,
      "timestamp naming is unambiguous UTC")

# 0045-FEAT: the role entry point now imports phase files.  Resolve those static
# imports so safety assertions examine the *active* tasks rather than only
# main.yaml (which contains no timer operations after the refactor).
def read_effective_tasks(entry: Path):
    role_tasks_dir = TASKS.parent.resolve()
    visited = []
    tasks = []

    def expand(path: Path, ancestors: tuple[Path, ...]):
        path = path.resolve()
        if not path.is_relative_to(role_tasks_dir):
            raise AssertionError(f"Task import escapes snapshot role: {path}")
        if path in ancestors:
            raise AssertionError(f"Cyclic snapshot task import: {path}")

        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, list):
            raise AssertionError(f"Expected task list in {path}")
        visited.append(path)
        for task in parsed:
            if not isinstance(task, dict):
                raise AssertionError(f"Expected task mapping in {path}: {task!r}")
            imported = task.get("ansible.builtin.import_tasks", task.get("import_tasks"))
            if imported is not None:
                if not isinstance(imported, str) or "{{" in imported:
                    raise AssertionError(f"Non-static snapshot task import: {task!r}")
                # Original per-task tags/guards must remain with their tasks,
                # rather than being changed by an import-level wrapper.
                if set(task) - {"name", "ansible.builtin.import_tasks", "import_tasks"}:
                    raise AssertionError(f"Snapshot import introduces controls: {task!r}")
                expand(path.parent / imported, ancestors + (path,))
            else:
                tasks.append(task)

    expand(entry, ())
    return tasks, "\n".join(path.read_text(encoding="utf-8") for path in visited)


effective_tasks, text = read_effective_tasks(TASKS)
check(len(effective_tasks) == 24,
      "all 24 native snapshot tasks are reachable through static imports")

defaults = DEFAULTS.read_text(encoding="utf-8")
check("btrfs_snapshot_activation_enabled: false" in defaults,
      "native snapshot activation is default-off")

# Each systemd task that *changes* a snapshot timer's active state must be
# individually guarded.  A textual match elsewhere in the role is insufficient.
timer_tasks = [
    task for task in effective_tasks
    if isinstance(task.get("ansible.builtin.systemd", task.get("systemd")), dict)
    and task.get("ansible.builtin.systemd", task.get("systemd", {})).get("name")
    in {"btrfs-snapshot-create.timer", "btrfs-snapshot-prune.timer"}
]
check(len(timer_tasks) == 2 and all(
    task.get("when") == "btrfs_snapshot_activation_enabled | bool"
    and "enabled" in task.get("ansible.builtin.systemd", task.get("systemd"))
    and "state" in task.get("ansible.builtin.systemd", task.get("systemd"))
    for task in timer_tasks
), "native timer enablement is behind explicit activation")
check("Install systemd units without activating them" in text,
      "ordinary deployment installs/preflights units without scheduling")
check("refusing to repurpose or delete it automatically" in text,
      "Ansible fails closed if @snapshots is an unexpected ordinary path")
check("Install Diaries backup-history tool" in text and HISTORY.exists(),
      "Playbooks installs the read-only Diaries snapshot-history tool")
check("Install Btrfs extent-sharing acceptance tool" in text and EXTENT_TOOL.exists(),
      "Playbooks installs the physical-extent sharing acceptance tool")

manager_text = MANAGER.read_text(encoding="utf-8")
check('["btrfs", "subvolume", "snapshot", "-r"' in manager_text,
      "manager creates read-only native Btrfs snapshots")
check("same Btrfs filesystem" in manager_text,
      "manager rejects cross-filesystem snapshot repository")
check("read_verified_diaries" in manager_text and "snapshotEligible" in manager_text,
      "manager requires the verified Diaries marker when integration is enabled")
check("writer_lock_path" in manager_text and "shared=True" in manager_text,
      "snapshot creation shares the receiver writer lock")
check("managed_snapshot_sets" in manager_text and "refusing retention with incomplete timestamp sets" in manager_text,
      "retention operates on complete multi-source timestamp sets and fails closed on partial sets")

readme = README.read_text(encoding="utf-8")

local_text = COLLECTION.read_text(encoding="utf-8")
remote_text = REMOTE_BACKUP.read_text(encoding="utf-8")
snapshot_playbook = SNAPSHOT_PLAYBOOK.read_text(encoding="utf-8")
snapshot_script = SNAPSHOT_SCRIPT.read_text(encoding="utf-8")
check("name: snapshots" in local_text, "mars/backup-collection uses the shared snapshots role")
check("name: snapshots" in remote_text, "backup/btrfs-replication uses the shared snapshots role")
check("- role: backup-collection" in snapshot_playbook and "- role: btrfs-replication" in snapshot_playbook,
      "snapshot entry point retains source and receiver safety contexts")
check('host="mars"' in snapshot_script and 'mars|backup' in snapshot_script,
      "snapshot launcher explicitly supports mars-first then backup deployment")

print("PASS: 0035 native Btrfs snapshot-manager regression verified")

check('require_existing=True' in manager_text and 'os.O_NOFOLLOW' in manager_text,
      "verified receiver snapshot creation requires pre-provisioned non-symlink writer lock")

check("btrfs-legacy-prune" not in text, "role cannot reinstall retired legacy-prune units")
check("legacy-prune" not in manager_text and "legacy-delete" not in manager_text, "manager does not expose retired legacy commands")
