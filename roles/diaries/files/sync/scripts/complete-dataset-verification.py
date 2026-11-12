#!/usr/bin/env python3
"""Prepare Step-4 verification artifacts for a captured Diaries complete dataset.

This helper is intentionally data-plane only: it hashes the two database dumps,
checks the plain SQL dump is readable pg_dump text, builds the durable Files
inventory/hash list, and proves the captured Files snapshot still exactly matches
the quiesced source Files root. PostgreSQL custom-dump structural validation is
performed by the PowerShell orchestrator using pg_restore --list from the selected
diaries-db container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Iterable

STAGING_NAME = ".image-staging"
DATABASE_CUSTOM = "database/diaries.dump"
DATABASE_SQL = "database/diaries.sql"
VERIFICATION_DIR = "verification"
DATABASE_HASHES = "verification/database.sha256"
FILES_HASHES = "verification/files.sha256"
INVENTORY = "verification/inventory.json"


class VerificationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def reject_links(path: Path, label: str) -> None:
    require(not path.is_symlink(), f"{label} must not contain symbolic links: {path}")


def iter_durable_files(root: Path, *, source: bool) -> Iterable[Path]:
    require(root.is_dir(), f"{'source Files root' if source else 'captured Files snapshot'} does not exist: {root}")
    reject_links(root, "Files tree")
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        # Only the root transient staging directory is outside the durable dataset.
        if source and current_path == root:
            dirs[:] = [name for name in dirs if name != STAGING_NAME]
        if not source and current_path == root and STAGING_NAME in dirs:
            raise VerificationError("captured Files snapshot must exclude transient .image-staging")
        for dirname in list(dirs):
            reject_links(current_path / dirname, "Files tree")
        for filename in files:
            path = current_path / filename
            reject_links(path, "Files tree")
            require(path.is_file(), f"Files tree contains a non-regular file: {path}")
            yield path


def inventory_for(root: Path, *, source: bool) -> dict[str, tuple[int, str]]:
    result: dict[str, tuple[int, str]] = {}
    for path in iter_durable_files(root, source=source):
        rel = path.relative_to(root).as_posix()
        media_rel = f"files/{rel}"
        result[media_rel] = (path.stat().st_size, sha256_file(path))
    return dict(sorted(result.items()))


def validate_sql_dump(path: Path) -> None:
    require(path.is_file(), f"missing SQL dump: {path}")
    require(path.stat().st_size > 0, f"SQL dump is empty: {path}")
    raw = path.read_bytes()
    require(b"\x00" not in raw, "SQL dump contains NUL bytes and is not a readable plain pg_dump")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise VerificationError("SQL dump is not readable UTF-8 plain pg_dump text") from exc
    require("PostgreSQL database dump" in text[:8192], "SQL dump is missing the PostgreSQL pg_dump header")
    require("PostgreSQL database dump complete" in text[-16384:], "SQL dump is missing the PostgreSQL pg_dump completion marker")


def prepare(backup_dir: Path, source_files_root: Path) -> tuple[int, int]:
    backup_dir = backup_dir.resolve()
    source_files_root = source_files_root.resolve()
    require(backup_dir.is_dir(), f"candidate backup workspace does not exist: {backup_dir}")

    custom = backup_dir / DATABASE_CUSTOM
    sql = backup_dir / DATABASE_SQL
    captured_files = backup_dir / "files"
    require(custom.is_file() and custom.stat().st_size > 0, f"missing/empty custom dump: {custom}")
    validate_sql_dump(sql)

    # Compare fully hashed inventories before writing any verification artifact.
    source_inventory = inventory_for(source_files_root, source=True)
    captured_inventory = inventory_for(captured_files, source=False)
    require(
        source_inventory == captured_inventory,
        "captured Files snapshot does not exactly match the current quiesced durable source Files paths, sizes and SHA-256 hashes",
    )

    inventory_entries = [
        {"path": rel, "sizeBytes": size, "sha256": digest}
        for rel, (size, digest) in captured_inventory.items()
    ]
    file_count = len(inventory_entries)
    total_bytes = sum(item["sizeBytes"] for item in inventory_entries)
    inventory_doc = {
        "schemaVersion": 1,
        "root": "files",
        "fileCount": file_count,
        "totalBytes": total_bytes,
        "files": inventory_entries,
    }

    database_hashes = (
        f"{sha256_file(custom)}  {DATABASE_CUSTOM}\n"
        f"{sha256_file(sql)}  {DATABASE_SQL}\n"
    )
    files_hashes = "".join(f"{item['sha256']}  {item['path']}\n" for item in inventory_entries)

    verification_dir = backup_dir / VERIFICATION_DIR
    verification_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(backup_dir / DATABASE_HASHES, database_hashes)
    atomic_write(backup_dir / FILES_HASHES, files_hashes)
    atomic_write(backup_dir / INVENTORY, json.dumps(inventory_doc, indent=2) + "\n")
    return file_count, total_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--source-files-root", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        count, total = prepare(Path(args.backup_dir), Path(args.source_files_root))
        print("Prepared complete-dataset verification artifacts")
        print(f"  Durable files: {count}")
        print(f"  Total bytes:   {total}")
        print("  Source match:  exact paths/sizes/SHA-256")
        print("  SQL dump:      readable PostgreSQL plain dump")
        return 0
    except (VerificationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
