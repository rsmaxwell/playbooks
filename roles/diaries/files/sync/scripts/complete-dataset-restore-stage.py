#!/usr/bin/env python3
"""Verify a Step-5 staged Files tree against a completed Diaries backup inventory.

The complete backup itself is validated separately with complete-dataset-manifest.py.
This helper proves that a newly copied restore staging tree contains exactly the
backup's durable Files paths, sizes and SHA-256 values before Step 6 is allowed
to replace the live Files root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

STAGING_NAME = ".image-staging"
MANIFEST = "dataset-manifest.json"
INVENTORY = "verification/inventory.json"


class StageError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StageError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    require(path.is_file(), f"required JSON file is missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StageError(f"cannot read JSON file {path}: {exc}") from exc


def expected_inventory(backup_dir: Path) -> dict[str, tuple[int, str]]:
    manifest = load_json(backup_dir / MANIFEST)
    require(manifest.get("schemaVersion") == 2, "restore staging requires schemaVersion 2")
    require(manifest.get("backupType") == "complete-dataset", "restore staging requires backupType=complete-dataset")
    require(manifest.get("completeDatasetBackup") is True, "restore staging requires completeDatasetBackup=true")
    require(manifest.get("status") == "complete", "restore staging requires status=complete")

    inventory_rel = (
        manifest.get("files", {})
        .get("snapshot", {})
        .get("inventoryPath")
    )
    require(inventory_rel == INVENTORY, f"unexpected Files inventory path: {inventory_rel!r}")
    inventory = load_json(backup_dir / INVENTORY)
    require(inventory.get("schemaVersion") == 1, "unsupported Files inventory schema")
    require(inventory.get("root") == "files", "Files inventory root must be 'files'")

    result: dict[str, tuple[int, str]] = {}
    for item in inventory.get("files", []):
        require(isinstance(item, dict), "Files inventory entry must be an object")
        media_path = item.get("path")
        size = item.get("sizeBytes")
        digest = item.get("sha256")
        require(isinstance(media_path, str) and media_path.startswith("files/"), f"invalid Files inventory path: {media_path!r}")
        rel = media_path[len("files/"):]
        require(rel and not rel.startswith("/") and "\\" not in rel, f"invalid staged relative path: {rel!r}")
        require(".." not in Path(rel).parts, f"escaping staged relative path: {rel!r}")
        require(isinstance(size, int) and size >= 0, f"invalid size for {media_path}")
        require(isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), f"invalid SHA-256 for {media_path}")
        require(rel not in result, f"duplicate Files inventory path: {media_path}")
        result[rel] = (size, digest)

    require(len(result) == inventory.get("fileCount"), "Files inventory fileCount does not match entries")
    require(sum(size for size, _ in result.values()) == inventory.get("totalBytes"), "Files inventory totalBytes does not match entries")
    return dict(sorted(result.items()))


def actual_inventory(stage_root: Path, allow_benign_runtime_staging: bool = False) -> dict[str, tuple[int, str]]:
    require(stage_root.is_dir(), f"staged Files root does not exist: {stage_root}")
    require(not stage_root.is_symlink(), f"staged Files root must not be a symbolic link: {stage_root}")
    result: dict[str, tuple[int, str]] = {}
    for current, dirs, files in os.walk(stage_root, topdown=True, followlinks=False):
        current_path = Path(current)
        if current_path == stage_root and STAGING_NAME in dirs:
            staging = stage_root / STAGING_NAME
            if not allow_benign_runtime_staging:
                raise StageError("staged replacement Files tree must not contain transient .image-staging")
            entries = list(staging.iterdir())
            benign = (
                len(entries) == 0
                or (
                    len(entries) == 1
                    and entries[0].name == "catalogue.lock"
                    and entries[0].is_file()
                    and not entries[0].is_symlink()
                    and entries[0].stat().st_size == 0
                )
            )
            require(benign, "runtime .image-staging must be empty or contain only zero-byte catalogue.lock")
            dirs.remove(STAGING_NAME)
        for dirname in dirs:
            path = current_path / dirname
            require(not path.is_symlink(), f"staged Files tree must not contain symbolic links: {path}")
        for filename in files:
            path = current_path / filename
            require(not path.is_symlink(), f"staged Files tree must not contain symbolic links: {path}")
            require(path.is_file(), f"staged Files tree contains a non-regular file: {path}")
            rel = path.relative_to(stage_root).as_posix()
            result[rel] = (path.stat().st_size, sha256_file(path))
    return dict(sorted(result.items()))


def verify(backup_dir: Path, stage_root: Path, allow_benign_runtime_staging: bool = False) -> tuple[int, int]:
    backup_dir = backup_dir.resolve()
    stage_root = stage_root.resolve()
    expected = expected_inventory(backup_dir)
    actual = actual_inventory(stage_root, allow_benign_runtime_staging=allow_benign_runtime_staging)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(path for path in set(expected) & set(actual) if expected[path] != actual[path])
        details = []
        if missing:
            details.append("missing=" + ", ".join(missing[:5]))
        if extra:
            details.append("extra=" + ", ".join(extra[:5]))
        if changed:
            details.append("changed=" + ", ".join(changed[:5]))
        raise StageError("staged Files tree does not exactly match backup inventory" + (": " + "; ".join(details) if details else ""))
    return len(expected), sum(size for size, _ in expected.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--staged-files-root", required=True)
    parser.add_argument("--allow-benign-runtime-staging", action="store_true", help="ignore only an empty .image-staging or zero-byte catalogue.lock while verifying the durable tree")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        count, total = verify(Path(args.backup_dir), Path(args.staged_files_root), allow_benign_runtime_staging=args.allow_benign_runtime_staging)
        print("Valid staged Diaries replacement Files tree")
        print(f"  Files:       {count}")
        print(f"  Total bytes: {total}")
        print("  Inventory:   exact paths/sizes/SHA-256")
        print("  Staging:     benign runtime .image-staging ignored" if args.allow_benign_runtime_staging else "  Staging:     transient .image-staging absent")
        return 0
    except (StageError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
