#!/usr/bin/env python3
"""Regression checks for the frozen production database-only backup/restore contract."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROLE = Path(__file__).resolve().parents[1]
SCRIPTS = ROLE / "files/sync/scripts"
BACKUPS = ("backup-db-to-binary.sh", "backup-db-to-sql.sh")
RESTORES = ("restore-db-from-binary.sh", "restore-db-from-sql.sh")
failures: list[str] = []


def check(ok: bool, message: str) -> None:
    if ok:
        print(f"PASS: {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def main() -> int:
    tool = SCRIPTS / "dataset-backup-manifest.py"
    check(tool.is_file(), "production deployment includes dataset manifest helper")

    tool_text = tool.read_text(encoding="utf-8") if tool.is_file() else ""
    check('"dataset": "production"' in tool_text and '"database_data": "docker-volume:diaries-db-data"' in tool_text,
          "production effective database identity is frozen as production / docker-volume:diaries-db-data")
    check('"DIARIES_FILES_DIR"' in tool_text and 'files_root = f"//{env[\'DIARIES_NAS_HOST\']}' in tool_text,
          "production Files identity is resolved from the deployed .env selector and NAS settings")
    check('"backupType": "database-only"' in tool_text and '"completeDatasetBackup": False' in tool_text and
          '"filesSnapshot": None' in tool_text,
          "production sidecar schema remains explicitly database-only")
    for field in ("logicalDataset", "effectiveDatabaseDataDir", "databaseBackupFile", "databaseBackupFormat",
                  "effectiveFilesDir", "resolvedPhysicalFilesRoot", "applicationSourceIdentity",
                  "imageRowCount", "cataloguedFileCount"):
        check(field in tool_text, f"production sidecar records {field}")
    check("legacy database backup" in tool_text and "verify the matching mutable Files root manually" in tool_text,
          "legacy production database backups remain usable with an explicit Files warning")

    backup_texts: dict[str, str] = {}
    for name in BACKUPS:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        backup_texts[name] = text
        check('BACKUP_DIR="${PROJECT_DIR}/data/database-backups/production"' in text,
              f"{name} keeps the production database-backup namespace")
        check('DB_SERVICE="${DIARIES_DB_SERVICE:-diaries-db}"' in text,
              f"{name} defaults database work to diaries-db")
        check("DATABASE-ONLY backup" in text, f"{name} labels database-only semantics")
        check("dataset-backup-manifest.py" in text and " write " in text, f"{name} writes a sidecar manifest")
        check("SELECT count(*) FROM public.image;" in text, f"{name} records Image row count")
        check("mutable Files bytes are not included" in text, f"{name} does not claim a complete dataset backup")
        check("diaries-production-${TIMESTAMP}" in text, f"{name} keeps production timestamped filename semantics")
        check('exec -T "${DB_SERVICE}" \\\n    pg_dump' in text,
              f"{name} performs pg_dump inside the configured database service")

    check("--format=custom" in backup_texts.get("backup-db-to-binary.sh", ""),
          "production binary backup remains PostgreSQL custom format")
    check("--format=plain" in backup_texts.get("backup-db-to-sql.sh", ""),
          "production SQL backup remains PostgreSQL plain format")

    restore_texts: dict[str, str] = {}
    for name in RESTORES:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        restore_texts[name] = text
        check('BACKUP_DIR="${PROJECT_DIR}/data/database-backups/production"' in text,
              f"{name} keeps the production database-backup namespace")
        check('DB_SERVICE="${DIARIES_DB_SERVICE:-diaries-db}"' in text,
              f"{name} defaults restore database work to diaries-db")
        check('APPLICATION_SERVICE="${DIARIES_RESPONDER_SERVICE:-diaries-responder}"' in text,
              f"{name} identifies diaries-responder as the application writer")
        check("DATABASE-ONLY restore" in text, f"{name} labels database-only semantics")
        check("dataset-backup-manifest.py" in text and " verify " in text, f"{name} verifies sidecar pairing")
        check("mutable Files bytes will not be restored" in text, f"{name} does not claim a complete dataset restore")
        check('read -r -p "Type RESTORE to continue: " ANSWER' in text,
              f"{name} requires explicit destructive confirmation")
        check('stop "${APPLICATION_SERVICE}"' in text and 'up --detach "${APPLICATION_SERVICE}"' in text,
              f"{name} stops a running responder and restores its prior running state after success")
        check("APPLICATION_WAS_RUNNING=false" in text and
              'Database restore failed; ${APPLICATION_SERVICE} has been left stopped.' in text,
              f"{name} leaves responder stopped after restore failure")

    check("pg_restore --list" in restore_texts.get("restore-db-from-binary.sh", "") and
          "pg_restore --exit-on-error" in restore_texts.get("restore-db-from-binary.sh", ""),
          "production binary restore validates and restores with pg_restore")
    check("psql -X -v ON_ERROR_STOP=1" in restore_texts.get("restore-db-from-sql.sh", ""),
          "production SQL restore applies the dump through psql with ON_ERROR_STOP")

    if tool.is_file():
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / ".env").write_text(
                "DIARIES_NAS_HOST=nas.localdomain\n"
                "DIARIES_NAS_SHARE=photo\n"
                "DIARIES_NAS_CONTENT_PATH=content/diaries\n"
                "DIARIES_FILES_DIR=files\n"
                "DIARIES_DB_NAME=diaries\n", encoding="utf-8")
            backup = project / "sample.dump"
            backup.write_bytes(b"not-empty")
            describe = subprocess.run([sys.executable, str(tool), "describe", "--project-dir", str(project)],
                                      text=True, capture_output=True)
            context = json.loads(describe.stdout) if describe.returncode == 0 else {}
            check(context == {
                    "dataset": "production",
                    "database_data": "docker-volume:diaries-db-data",
                    "database_name": "diaries",
                    "files_dir": "files",
                    "files_root": "//nas.localdomain/photo/content/diaries/files",
                  }, "production helper resolves the frozen effective database + Files pair")

            result = subprocess.run([sys.executable, str(tool), "write", "--project-dir", str(project),
                                     "--backup-file", str(backup), "--backup-format", "custom",
                                     "--image-row-count", "42", "--runtime-images", "responder:1\nclient:2"],
                                    text=True, capture_output=True)
            check(result.returncode == 0, "manifest helper writes a production database sidecar")
            manifest_path = Path(str(backup) + ".dataset.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            check(manifest.get("schemaVersion") == 1 and
                  manifest.get("backupType") == "database-only" and manifest.get("completeDatasetBackup") is False and
                  manifest.get("filesSnapshot") is None,
                  "production sidecar explicitly freezes schema-1 database-only semantics")
            check(manifest.get("logicalDataset") == "production" and
                  manifest.get("effectiveDatabaseDataDir") == "docker-volume:diaries-db-data",
                  "production sidecar records the effective database identity")
            check(manifest.get("effectiveFilesDir") == "files" and
                  manifest.get("resolvedPhysicalFilesRoot") == "//nas.localdomain/photo/content/diaries/files",
                  "production sidecar records the effective Files selector and physical root")
            check(manifest.get("imageRowCount") == 42 and manifest.get("cataloguedFileCount") == 42,
                  "production sidecar records catalogue count")
            verify = subprocess.run([sys.executable, str(tool), "verify", "--project-dir", str(project),
                                     "--backup-file", str(backup)], text=True, capture_output=True)
            check(verify.returncode == 0, "matching production database + Files pair verifies")
            env = (project / ".env").read_text(encoding="utf-8").replace("DIARIES_FILES_DIR=files", "DIARIES_FILES_DIR=files-other")
            (project / ".env").write_text(env, encoding="utf-8")
            mismatch = subprocess.run([sys.executable, str(tool), "verify", "--project-dir", str(project),
                                       "--backup-file", str(backup)], text=True, capture_output=True)
            check(mismatch.returncode != 0 and "mismatch" in mismatch.stderr.lower(),
                  "production restore guard rejects a mismatched Files root")

            legacy = project / "legacy.dump"
            legacy.write_bytes(b"not-empty")
            legacy_verify = subprocess.run([sys.executable, str(tool), "verify", "--project-dir", str(project),
                                            "--backup-file", str(legacy)], text=True, capture_output=True)
            check(legacy_verify.returncode == 0 and "DATABASE-ONLY restore" in legacy_verify.stderr,
                  "production legacy backup compatibility warning remains non-fatal")

    if failures:
        print(f"FAILED: {len(failures)} production backup/restore check(s)", file=sys.stderr)
        return 1
    print("PASS: production database-only backup/restore and effective-dataset contract frozen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
