#!/usr/bin/env python3
"""Regression checks for the production database/Files storage-isolation contract."""

from pathlib import Path
import importlib.util
import sys

ROLE = Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"PASS: {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def text(relative: str) -> str:
    return (ROLE / relative).read_text(encoding="utf-8")


def main() -> int:
    compose = text("templates/compose.yaml.j2")
    env = text("templates/.env.j2")
    defaults = text("defaults/main.yaml")
    main_tasks = text("tasks/main.yaml")
    copy_tasks = text("tasks/copy.yaml")
    engine_path = ROLE / "files/sync/scripts/production-complete-dataset.py"
    engine = engine_path.read_text(encoding="utf-8")

    check("DIARIES_FILES_DIR={{ diaries_files_dir }}" in env,
          "production .env renders the explicit diaries_files_dir selector")
    check("subpath: ${DIARIES_NAS_CONTENT_PATH}/${DIARIES_FILES_DIR}" in compose,
          "production mutable /data/files mount is selected through DIARIES_FILES_DIR")
    check("subpath: ${DIARIES_NAS_CONTENT_PATH}/diaries" in compose,
          "production shared diary scans remain on the common /diaries source")
    check("subpath: ${DIARIES_NAS_CONTENT_PATH}/files" not in compose,
          "production template has no hard-coded mutable /files source")
    check("diaries_files_dir:" not in "\n".join(
              line for line in defaults.splitlines() if not line.lstrip().startswith("#")),
          "role defaults do not silently fall back to the production Files selector")
    check("diaries_files_dir is defined" in main_tasks and
          "diaries_files_dir must be explicitly supplied" in main_tasks,
          "role preflight requires an explicit mutable Files selector")
    check("Validate rendered mutable Files selector in .env" in copy_tasks and
          "Validate rendered mutable Files mount in Compose" in copy_tasks,
          "deployment validates the rendered selector and mutable Files mount")
    check("Validate rendered shared diary scan mount in Compose" in copy_tasks,
          "deployment validates that shared scans remain on /diaries")

    check('diaries_complete_backup_repository_root: "{{ diaries_project_dir }}/data/dataset-backups/production"' in defaults and
          'diaries_complete_restore_state_root: "{{ diaries_project_dir }}/data/dataset-restores/production"' in defaults,
          "0034 Step 2 defaults preserve the frozen 0033 backup/restore locations")
    check('diaries_complete_backup_published_root: "{{ diaries_project_dir }}/data/diaries-backup"' in defaults,
          "0034 Step 8 defines a stable publication path separate from the legacy repository")
    check("diaries_complete_backup_storage_mode: auto" in defaults,
          "0034 Step 2 storage mode is retained for historical capture compatibility")
    check("diaries_complete_backup_storage_mode in ['auto', 'required-btrfs', 'full-copy']" in main_tasks,
          "Ansible accepts exactly the three supported storage-mode values")
    check("diaries_complete_backup_repository_root is match('^/')" in main_tasks and
          "diaries_complete_restore_state_root is match('^/')" in main_tasks and
          "diaries_complete_backup_repository_root != diaries_complete_restore_state_root" in main_tasks,
          "Ansible requires distinct absolute complete-backup and restore-state roots")
    check("DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT={{ diaries_complete_backup_repository_root }}" in env and
          "DIARIES_COMPLETE_RESTORE_STATE_ROOT={{ diaries_complete_restore_state_root }}" in env and
          "DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT={{ diaries_complete_backup_published_root }}" in env and
          "DIARIES_COMPLETE_BACKUP_STORAGE_MODE={{ diaries_complete_backup_storage_mode }}" in env,
          "production .env renders the complete-dataset repository/state/publication/storage inputs")
    check('{{ diaries_complete_backup_repository_root }}' in copy_tasks and
          '{{ diaries_complete_restore_state_root }}' in copy_tasks and
          "Validate rendered complete-dataset storage contract in .env" in copy_tasks,
          "deployment creates and verifies the configured backup/state roots rather than fixed production leaves")
    check('self._configured_absolute_path("DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT")' in engine and
          'self._configured_absolute_path("DIARIES_COMPLETE_RESTORE_STATE_ROOT")' in engine and
          'self._configured_absolute_path("DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT")' in engine and
          'self.env["DIARIES_COMPLETE_BACKUP_STORAGE_MODE"]' in engine,
          "production complete-dataset tooling consumes repository/state/publication/mode inputs")
    check('self.project / "data" / "dataset-backups"' not in engine and
          'self.project / "data" / "dataset-restores"' not in engine,
          "production backup code no longer infers complete-dataset roots from project layout")

    try:
        spec = importlib.util.spec_from_file_location("production_complete_dataset_step2", engine_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load production complete-dataset engine for contract checks")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        Production = module.Production
        ToolError = module.ToolError

        def validate(mode: str, backup: str = "/srv/diaries-backups", restore: str = "/home/richard/projects/diaries/data/dataset-restores/production") -> bool:
            obj = Production.__new__(Production)
            obj.storage_mode = mode
            obj.backup_root = Path(backup)
            obj.restore_root = Path(restore)
            obj.published_root = Path("/srv/diaries-current")
            obj.context = {"files_root": "/srv/live-files"}
            try:
                obj._validate_complete_storage_contract()
                return True
            except ToolError:
                return False

        for mode in ("auto", "required-btrfs", "full-copy"):
            check(validate(mode), f"runtime storage-contract validation accepts mode {mode}")
        for mode in ("", "btrfs", "automatic", "AUTO"):
            check(not validate(mode), f"runtime storage-contract validation rejects invalid mode {mode!r}")
        check(not validate("auto", "/srv/diaries", "/srv/diaries"),
              "runtime storage-contract validation rejects identical backup/restore roots")
        check(not validate("auto", "/srv/diaries", "/srv/diaries/restore-state"),
              "runtime storage-contract validation rejects restore state nested inside backup repository")
        check(not validate("auto", "/srv/diaries/backups", "/srv/diaries"),
              "runtime storage-contract validation rejects backup repository nested inside restore state")
        obj = Production.__new__(Production)
        obj.storage_mode = "auto"
        obj.backup_root = Path("/srv/legacy")
        obj.restore_root = Path("/srv/state")
        obj.published_root = Path("/srv/legacy/diaries-backup")
        obj.context = {"files_root": "/srv/live-files"}
        try:
            obj._validate_complete_storage_contract()
            publication_overlap_rejected = False
        except ToolError:
            publication_overlap_rejected = True
        check(publication_overlap_rejected,
              "runtime storage-contract validation rejects stable publication nested in legacy repository")
        obj = Production.__new__(Production)
        obj.storage_mode = "auto"
        obj.backup_root = Path("/srv/legacy")
        obj.restore_root = Path("/srv/state")
        obj.published_root = Path("/srv/live-files/current")
        obj.context = {"files_root": "/srv/live-files"}
        try:
            obj._validate_complete_storage_contract()
            files_overlap_rejected = False
        except ToolError:
            files_overlap_rejected = True
        check(files_overlap_rejected,
              "runtime storage-contract validation rejects publication overlapping mutable source Files")
    except Exception as exc:
        check(False, f"runtime storage-contract validation could not be exercised: {exc}")

    if failures:
        print(f"FAILED: {len(failures)} production storage-isolation regression check(s)", file=sys.stderr)
        return 1
    print("PASS: production storage-isolation contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
