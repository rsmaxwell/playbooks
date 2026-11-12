#!/usr/bin/env python3
"""Regression tests for the permanent complete-dataset backup manifest contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROLE = Path(__file__).resolve().parents[1]
TOOL = ROLE / "files/sync/scripts/complete-dataset-manifest.py"
BACKUP_ID = "20261007-120000Z"
failures: list[str] = []


def check(ok: bool, message: str) -> None:
    if ok:
        print(f"PASS: {message}")
    else:
        failures.append(message)
        print(f"FAIL: {message}")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], text=True, capture_output=True)


def create_candidate(base: Path) -> Path:
    root = base / f".{BACKUP_ID}.partial"
    (root / "database").mkdir(parents=True)
    (root / "files/nested").mkdir(parents=True)
    (root / "verification").mkdir(parents=True)
    (root / "database/diaries.dump").write_bytes(b"synthetic-postgresql-custom-dump\n")
    (root / "database/diaries.sql").write_text("-- PostgreSQL database dump\nSELECT 1;\n", encoding="utf-8")
    (root / "files/a.txt").write_text("alpha\n", encoding="utf-8")
    (root / "files/nested/b.bin").write_bytes(bytes(range(32)))

    file_paths = [root / "files/a.txt", root / "files/nested/b.bin"]
    inventory_entries = [
        {"path": path.relative_to(root).as_posix(), "sizeBytes": path.stat().st_size, "sha256": sha(path)}
        for path in file_paths
    ]
    inventory = {
        "schemaVersion": 1,
        "root": "files",
        "fileCount": len(inventory_entries),
        "totalBytes": sum(item["sizeBytes"] for item in inventory_entries),
        "files": inventory_entries,
    }
    (root / "verification/inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    (root / "verification/database.sha256").write_text(
        f"{sha(root / 'database/diaries.dump')}  database/diaries.dump\n"
        f"{sha(root / 'database/diaries.sql')}  database/diaries.sql\n",
        encoding="utf-8",
    )
    (root / "verification/files.sha256").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in inventory_entries),
        encoding="utf-8",
    )
    return root


def write_manifest(root: Path) -> subprocess.CompletedProcess[str]:
    return run(
        "write", "--backup-dir", str(root),
        "--logical-dataset", "common",
        "--launch-mode", "local-docker-build",
        "--known-consumer", "development-infrastructure",
        "--known-consumer", "local-docker-build",
        "--known-consumer", "local-published-smoke",
        "--database-storage-identity", "./data/database/common",
        "--database-name", "diaries",
        "--files-selector", "files-development-common",
        "--files-root", "//nas.localdomain/photo/content/diaries/files-development-common",
        "--application-identity-json", '{"gitCommit":"synthetic-step2"}',
        "--writer-method", "synthetic-fixture",
        "--writer", "diaries-responder",
        "--writer-evidence", "synthetic writer held quiesced for contract test",
        "--image-row-count", "2",
        "--catalogued-file-count", "2",
        "--staging-disposition", "empty",
        "--staging-entry-count", "0",
        "--staging-note", "synthetic source staging was empty and was excluded from the snapshot",
        "--started-at", "2026-10-07T11:59:00+00:00",
        "--completed-at", "2026-10-07T12:00:00+00:00",
    )


def mutate_manifest(root: Path, mutator) -> bytes:
    path = root / "dataset-manifest.json"
    original = path.read_bytes()
    doc = json.loads(original)
    mutator(doc)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return original


def rejection(root: Path, label: str, mutator, expected: str) -> None:
    manifest = root / "dataset-manifest.json"
    original = mutate_manifest(root, mutator)
    try:
        result = run("verify", "--backup-dir", str(root))
        check(result.returncode != 0 and expected.lower() in result.stderr.lower(), label)
    finally:
        manifest.write_bytes(original)


def main() -> int:
    check(TOOL.is_file(), "complete-dataset manifest generator/validator is present")
    if not TOOL.is_file():
        return 1

    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        partial = create_candidate(base)
        generated = write_manifest(partial)
        check(generated.returncode == 0, "synthetic complete manifest is generated from verified candidate components")
        manifest_path = partial / "dataset-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        check(manifest.get("schemaVersion") == 2 and manifest.get("backupType") == "complete-dataset" and
              manifest.get("completeDatasetBackup") is True and manifest.get("status") == "complete",
              "generated manifest freezes schema-2 complete-dataset completion markers")
        check(manifest.get("backupId") == BACKUP_ID and manifest.get("logicalDataset") == "common",
              "generated manifest records backup ID and effective logical dataset")
        check(manifest.get("database", {}).get("customDump", {}).get("path") == "database/diaries.dump" and
              manifest.get("database", {}).get("sqlDump", {}).get("path") == "database/diaries.sql" and
              manifest.get("files", {}).get("snapshot", {}).get("path") == "files",
              "generated manifest uses the frozen required component paths")
        check(manifest.get("counts", {}).get("durableFileCount") == 2 and
              manifest.get("files", {}).get("snapshot", {}).get("fileCount") == 2,
              "generated manifest records durable Files count from the verified inventory")
        check(manifest.get("writerQuiescence", {}).get("status") == "quiesced" and
              manifest.get("staging", {}).get("snapshotIncluded") is False,
              "generated manifest records writer quiescence and staging exclusion")

        normal_partial = run("verify", "--backup-dir", str(partial))
        check(normal_partial.returncode != 0 and "non-restorable" in normal_partial.stderr,
              "normal validation rejects .<backup-id>.partial as a restorable backup")
        candidate_verify = run("verify", "--backup-dir", str(partial), "--allow-partial-workspace")
        check(candidate_verify.returncode == 0 and "partial candidate" in candidate_verify.stdout,
              "backup finalisation can validate a complete candidate inside the partial workspace")

        final = base / BACKUP_ID
        partial.rename(final)
        completed_verify = run("verify", "--backup-dir", str(final))
        check(completed_verify.returncode == 0 and "completed backup" in completed_verify.stdout,
              "synthetic candidate validates normally after same-filesystem promotion to final backup ID")

        rejection(final, "unsupported complete-manifest schema is rejected",
                  lambda doc: doc.__setitem__("schemaVersion", 99), "unsupported schemaVersion")
        rejection(final, "wrong backupType is rejected",
                  lambda doc: doc.__setitem__("backupType", "database-only"), "backupType")
        rejection(final, "completeDatasetBackup=false is rejected",
                  lambda doc: doc.__setitem__("completeDatasetBackup", False), "completeDatasetBackup")
        rejection(final, "non-complete status is rejected",
                  lambda doc: doc.__setitem__("status", "partial"), "status")
        rejection(final, "invalid logical dataset identity is rejected",
                  lambda doc: doc.__setitem__("logicalDataset", "../common"), "logicalDataset")
        rejection(final, "absolute component path is rejected",
                  lambda doc: doc["database"]["customDump"].__setitem__("path", "/tmp/diaries.dump"), "relative")
        rejection(final, "escaping component path is rejected",
                  lambda doc: doc["database"]["customDump"].__setitem__("path", "../diaries.dump"), "..")
        rejection(final, "missing component hash is rejected",
                  lambda doc: doc["database"]["customDump"].pop("sha256"), "sha-256")
        rejection(final, "invalid component hash syntax is rejected",
                  lambda doc: doc["database"]["sqlDump"].__setitem__("sha256", "xyz"), "sha-256")

        sql = final / "database/diaries.sql"
        sql_bytes = sql.read_bytes()
        sql.unlink()
        missing = run("verify", "--backup-dir", str(final))
        check(missing.returncode != 0 and "missing required component" in missing.stderr.lower(),
              "missing required database component is rejected")
        sql.write_bytes(sql_bytes)

        file_path = final / "files/a.txt"
        file_bytes = file_path.read_bytes()
        file_path.write_bytes(file_bytes + b"corrupt")
        corrupt = run("verify", "--backup-dir", str(final))
        check(corrupt.returncode != 0 and "inventory" in corrupt.stderr.lower(),
              "Files byte corruption is rejected by inventory/hash validation")
        file_path.write_bytes(file_bytes)
        final_verify = run("verify", "--backup-dir", str(final))
        check(final_verify.returncode == 0, "synthetic backup returns to a valid complete state after negative cases")

    if failures:
        print(f"FAILED: {len(failures)} complete-dataset manifest contract check(s)", file=sys.stderr)
        return 1
    print("PASS: complete-dataset directory and manifest contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
