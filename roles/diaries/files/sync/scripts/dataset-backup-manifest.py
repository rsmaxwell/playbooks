#!/usr/bin/env python3
"""Step-7 database-backup sidecar manifest support for installed Diaries."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import shlex
import sys


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def context(project: Path) -> dict[str, str]:
    env_file = project / ".env"
    if not env_file.is_file():
        raise ValueError(f"Runtime environment file not found: {env_file}")
    env = read_env(env_file)
    required = ["DIARIES_NAS_HOST", "DIARIES_NAS_SHARE", "DIARIES_NAS_CONTENT_PATH", "DIARIES_FILES_DIR", "DIARIES_DB_NAME"]
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise ValueError("Missing required runtime value(s): " + ", ".join(missing))
    content = env["DIARIES_NAS_CONTENT_PATH"].strip("/\\")
    files_root = f"//{env['DIARIES_NAS_HOST']}/{env['DIARIES_NAS_SHARE']}/{content}/{env['DIARIES_FILES_DIR']}"
    return {
        "dataset": "production",
        "database_data": "docker-volume:diaries-db-data",
        "database_name": env["DIARIES_DB_NAME"],
        "files_dir": env["DIARIES_FILES_DIR"],
        "files_root": files_root,
    }


def describe(args: argparse.Namespace) -> int:
    ctx = context(Path(args.project_dir).resolve())
    if args.shell:
        for key, value in [
            ("DIARIES_DATASET_NAME", ctx["dataset"]),
            ("DIARIES_EFFECTIVE_DB_DATA", ctx["database_data"]),
            ("DIARIES_EFFECTIVE_FILES_DIR", ctx["files_dir"]),
            ("DIARIES_EFFECTIVE_FILES_ROOT", ctx["files_root"]),
        ]:
            print(f"{key}={shlex.quote(value)}")
    else:
        print(json.dumps(ctx, indent=2))
    return 0


def write_manifest(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    ctx = context(project)
    backup = Path(args.backup_file).resolve()
    if not backup.is_file() or backup.stat().st_size == 0:
        raise ValueError(f"Backup file is missing or empty: {backup}")
    count: int | str = int(args.image_row_count) if str(args.image_row_count).isdigit() else "unknown"
    images = [line.strip() for line in (args.runtime_images or "").splitlines() if line.strip()]
    manifest = {
        "schemaVersion": 1,
        "backupType": "database-only",
        "completeDatasetBackup": False,
        "createdAt": dt.datetime.now(dt.timezone.utc).astimezone().isoformat(),
        "launchMode": "production",
        "logicalDataset": ctx["dataset"],
        "effectiveDatabaseDataDir": ctx["database_data"],
        "databaseName": ctx["database_name"],
        "databaseBackupFile": backup.name,
        "databaseBackupFormat": args.backup_format,
        "effectiveFilesDir": ctx["files_dir"],
        "resolvedPhysicalFilesRoot": ctx["files_root"],
        "applicationSourceIdentity": {"runtimeImages": images},
        "imageRowCount": count,
        "cataloguedFileCount": count,
        "filesSnapshot": None,
        "note": "Database-only backup. No mutable Files bytes are included. Restore only with the matching Files root/snapshot.",
    }
    path = Path(str(backup) + ".dataset.json")
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(path)
    return 0


def verify(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    ctx = context(project)
    backup = Path(args.backup_file).resolve()
    path = Path(str(backup) + ".dataset.json")
    if not path.is_file():
        print(f"WARNING: No Step-7 dataset manifest exists for legacy database backup: {backup}", file=sys.stderr)
        print("WARNING: This is a DATABASE-ONLY restore; verify the matching mutable Files root manually.", file=sys.stderr)
        return 0
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("backupType") != "database-only" or manifest.get("completeDatasetBackup") is not False:
        raise ValueError(f"Unexpected backup manifest semantics: {path}")
    checks = {
        "logicalDataset": ctx["dataset"],
        "effectiveDatabaseDataDir": ctx["database_data"],
        "effectiveFilesDir": ctx["files_dir"],
        "resolvedPhysicalFilesRoot": ctx["files_root"],
    }
    for key, expected in checks.items():
        actual = str(manifest.get(key, ""))
        if actual != expected:
            raise ValueError(f"Dataset manifest mismatch for {key}: backup={actual!r}, current={expected!r}. Refusing restore.")
    print("Matched database-only backup manifest:")
    print(f"  Dataset:    {ctx['dataset']}")
    print(f"  Database:   {ctx['database_data']}")
    print(f"  Files dir:  {ctx['files_dir']}")
    print(f"  Files root: {ctx['files_root']}")
    print("  Files bytes: NOT included in this restore")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("describe")
    p.add_argument("--project-dir", required=True)
    p.add_argument("--shell", action="store_true")
    p.set_defaults(func=describe)
    p = sub.add_parser("write")
    p.add_argument("--project-dir", required=True)
    p.add_argument("--backup-file", required=True)
    p.add_argument("--backup-format", required=True)
    p.add_argument("--image-row-count", default="unknown")
    p.add_argument("--runtime-images", default="")
    p.set_defaults(func=write_manifest)
    p = sub.add_parser("verify")
    p.add_argument("--project-dir", required=True)
    p.add_argument("--backup-file", required=True)
    p.set_defaults(func=verify)
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
