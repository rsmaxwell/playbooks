#!/usr/bin/env python3
"""0034 Step 7 isolated restore-source compatibility regression.

Exercises the production restore selector without Docker or production mutation:
legacy backup IDs, the stable diaries-backup publication, explicit snapshot-like
paths, target mismatch refusal, exact RESTORE confirmation, and prepared-source
pinning for apply/rollback/postflight continuation.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import sys

ROLE = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROLE / "files/sync/scripts/production-complete-dataset.py"

spec = importlib.util.spec_from_file_location("production_complete_dataset", ENGINE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot import {ENGINE_PATH}")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"PASS: {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def write_fixture(root: Path, backup_id: str, logical_dataset: str = "production") -> Path:
    root.mkdir(parents=True, exist_ok=False)
    (root / "database").mkdir()
    (root / "files").mkdir()
    (root / "database/diaries.dump").write_bytes(b"synthetic-custom-dump")
    (root / "database/diaries.sql").write_bytes(
        b"-- PostgreSQL database dump\nSELECT 1;\n-- PostgreSQL database dump complete\n"
    )
    (root / "dataset-manifest.json").write_text(json.dumps({
        "schemaVersion": 2,
        "backupType": "complete-dataset",
        "completeDatasetBackup": True,
        "status": "complete",
        "backupId": backup_id,
        "logicalDataset": logical_dataset,
        "database": {"name": "diaries"},
        "files": {"snapshot": {"fileCount": 0, "totalBytes": 0}},
    }), encoding="utf-8")
    return root


class FakeProduction:
    def __init__(self, backup_root: Path, restore_root: Path, published_root: Path):
        self.backup_root = backup_root
        self.restore_root = restore_root
        self.published_root = published_root
        self.storage_mode = "full-copy"
        self.context = {
            "database_data": "docker-volume:diaries-db-data",
            "database_name": "diaries",
            "files_dir": "files",
            "files_root": "//nas/photo/diaries/files",
        }
        self.stop_calls = 0

    def manifest_verify(self, backup: Path):
        return json.loads((backup / "dataset-manifest.json").read_text(encoding="utf-8"))

    def assert_target_matches(self, manifest):
        if manifest.get("logicalDataset") != "production":
            engine.fail("complete backup target identity mismatch; refusing restore: logicalDataset")

    def assert_db_ready(self):
        return "diaries", "diaries"

    def pg_restore_list(self, dump: Path):
        if not dump.is_file():
            engine.fail("custom dump missing")

    def inspect_staging(self):
        return "absent", 0

    def rel_sibling(self, leaf: str):
        return f"content/{leaf}"

    def resolved_unc_sibling(self, leaf: str):
        return f"//nas/photo/diaries/{leaf}"

    def responder_running(self):
        return False

    def stop_responder(self):
        self.stop_calls += 1


def expect_tool_error(callable_, contains: str) -> bool:
    try:
        callable_()
    except engine.ToolError as exc:
        return contains.lower() in str(exc).lower()
    return False


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="0034-step7-") as td:
        base = Path(td)
        backup_root = base / "repository"
        restore_root = base / "restore-state"
        published_root = base / "diaries-backup"
        backup_root.mkdir(); restore_root.mkdir()
        p = FakeProduction(backup_root, restore_root, published_root)

        legacy_id = "20261001-010203Z"
        legacy = write_fixture(backup_root / legacy_id, legacy_id)
        selected_legacy = engine.resolve_backup(p, legacy_id)
        check(selected_legacy == legacy.resolve(), "legacy <backup-id>/ source still resolves unchanged")
        engine.preflight_restore(p, selected_legacy)
        check(True, "legacy source passes non-destructive restore preflight")

        fixed_id = "20261002-020304Z"
        store = base / ".diaries-backup-generations"
        store.mkdir()
        generation = write_fixture(store / fixed_id, fixed_id)
        published_root.symlink_to(Path(".diaries-backup-generations") / fixed_id)
        selected_fixed = engine.resolve_backup(p, "diaries-backup")
        check(selected_fixed == generation.resolve(), "bare diaries-backup selects the stable published current dataset")
        selected_fixed_slash = engine.resolve_backup(p, "diaries-backup/")
        check(selected_fixed_slash == generation.resolve(), "diaries-backup/ selector is accepted")
        engine.preflight_restore(p, selected_fixed)
        check(True, "fixed published source passes the same schema-2 preflight as legacy media")

        snapshot_id = "20261003-030405Z"
        snapshot = write_fixture(base / "snapshots/20261009-120000Z/diaries-backup", snapshot_id)
        selected_snapshot = engine.resolve_backup(p, str(snapshot))
        check(selected_snapshot == snapshot.resolve(), "explicit read-only/snapshot-style directory path is a restore entry point")
        engine.preflight_restore(p, selected_snapshot)
        check(True, "snapshot-style explicit source uses the unchanged restore preflight")

        mismatch_id = "20261004-040506Z"
        mismatch = write_fixture(base / "mismatch", mismatch_id, logical_dataset="other-dataset")
        check(expect_tool_error(lambda: engine.preflight_restore(p, mismatch), "target identity mismatch"),
              "logical dataset mismatch is still rejected before destructive work")

        with patch("builtins.input", return_value="restore"):
            check(expect_tool_error(lambda: engine.prepare_restore(p, selected_fixed), "exact restore token"),
                  "prepare still requires the exact uppercase RESTORE confirmation")
        check(p.stop_calls == 0, "failed RESTORE confirmation performs no writer stop or restore mutation")

        prepared_dir = restore_root / f"{fixed_id}.prepared"
        prepared_dir.mkdir()
        (prepared_dir / "restore-state.json").write_text(json.dumps({
            "feature": "0033-FEAT",
            "restoreSource": {"backupId": fixed_id, "directory": str(generation.resolve())},
        }), encoding="utf-8")

        # Create a conflicting legacy directory with the same ID. Continuation must
        # prefer the source pinned by prepare rather than silently switching media.
        conflicting_legacy = write_fixture(backup_root / fixed_id, fixed_id)
        (conflicting_legacy / "marker").write_text("different media", encoding="utf-8")
        continuation = engine.resolve_backup(p, fixed_id, prefer_prepared=True)
        check(continuation == generation.resolve(),
              "continuation by backup ID reuses the exact prepared source even when same-ID legacy media exists")

        # Move the public pointer to a newer generation. Prepared continuation must
        # remain pinned to the original immutable generation.
        newer_id = "20261005-050607Z"
        newer = write_fixture(store / newer_id, newer_id)
        published_root.unlink()
        published_root.symlink_to(Path(".diaries-backup-generations") / newer_id)
        current = engine.resolve_backup(p, "diaries-backup")
        continuation_after_advance = engine.resolve_backup(p, fixed_id, prefer_prepared=True)
        check(current == newer.resolve() and continuation_after_advance == generation.resolve(),
              "prepared restore remains pinned when diaries-backup advances to a newer generation")

        partial = base / ".20261006-060708Z.partial"
        partial.mkdir()
        check(expect_tool_error(lambda: engine.resolve_backup(p, str(partial)), "partial"),
              "partial workspaces remain non-restorable")

    if failures:
        print(f"FAILED: {len(failures)} Step 7 compatibility check(s)", file=sys.stderr)
        return 1
    print("PASS: 0034 Step 7 historical/fixed/snapshot restore-source compatibility contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
