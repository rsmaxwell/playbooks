#!/usr/bin/env python3
"""Generate and validate the Diaries complete-dataset backup manifest contract.

This helper deliberately does not create PostgreSQL dumps or copy mutable Files.
It describes and validates an already-captured candidate backup workspace.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {SCHEMA_VERSION}
MANIFEST_NAME = "dataset-manifest.json"
BACKUP_ID_RE = re.compile(r"^(\d{8})-(\d{6})Z$")
DATASET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATABASE_CUSTOM_PATH = "database/diaries.dump"
DATABASE_SQL_PATH = "database/diaries.sql"
DATABASE_HASHES_PATH = "verification/database.sha256"
FILES_ROOT_PATH = "files"
FILES_HASHES_PATH = "verification/files.sha256"
INVENTORY_PATH = "verification/inventory.json"
PARTIAL_PREFIX = "."
PARTIAL_SUFFIX = ".partial"


class ContractError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_backup_id(value: str) -> None:
    match = BACKUP_ID_RE.fullmatch(value)
    require(match is not None, "backupId must use UTC YYYYMMDD-HHmmssZ format")
    try:
        dt.datetime.strptime(value, "%Y%m%d-%H%M%SZ")
    except ValueError as exc:
        raise ContractError(f"backupId is not a real UTC timestamp: {value}") from exc


def backup_id_from_directory(directory: Path) -> tuple[str, bool]:
    name = directory.name
    if name.startswith(PARTIAL_PREFIX) and name.endswith(PARTIAL_SUFFIX):
        backup_id = name[len(PARTIAL_PREFIX):-len(PARTIAL_SUFFIX)]
        parse_backup_id(backup_id)
        return backup_id, True
    parse_backup_id(name)
    return name, False


def parse_iso_timestamp(value: Any, label: str) -> dt.datetime:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty ISO-8601 timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(f"{label} is not a valid ISO-8601 timestamp: {value}") from exc
    require(parsed.tzinfo is not None, f"{label} must include a timezone offset")
    return parsed


def canonical_relative_path(value: Any, label: str) -> str:
    require(isinstance(value, str) and value, f"{label} must be a non-empty relative path")
    require("\\" not in value, f"{label} must use '/' separators, not backslashes")
    require(not value.startswith("//"), f"{label} must not be a UNC/absolute path")
    require(re.match(r"^[A-Za-z]:", value) is None, f"{label} must not be a Windows absolute path")
    path = PurePosixPath(value)
    require(not path.is_absolute(), f"{label} must be relative")
    require(all(part not in ("", ".", "..") for part in path.parts), f"{label} must not contain empty, '.' or '..' segments")
    canonical = path.as_posix()
    require(canonical == value, f"{label} must be canonical POSIX-style relative path text")
    return canonical


def required_string(value: Any, label: str) -> str:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty string")
    return value.strip()


def required_nonnegative_int(value: Any, label: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value >= 0, f"{label} must be a non-negative integer")
    return value


def required_positive_int(value: Any, label: str) -> int:
    require(isinstance(value, int) and not isinstance(value, bool) and value > 0, f"{label} must be a positive integer")
    return value


def required_sha256(value: Any, label: str) -> str:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f"{label} must be a lowercase 64-hex SHA-256")
    return value


def member_path(root: Path, relative: str, label: str) -> Path:
    relative = canonical_relative_path(relative, label)
    target = root.joinpath(*PurePosixPath(relative).parts)
    # References must remain within the backup and must not traverse symlinks.
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.exists() or current.is_symlink():
            require(not current.is_symlink(), f"{label} must not traverse a symbolic link: {relative}")
    return target


def require_file(root: Path, relative: str, label: str) -> Path:
    path = member_path(root, relative, label)
    require(path.is_file(), f"missing required component {label}: {relative}")
    return path


def require_directory(root: Path, relative: str, label: str) -> Path:
    path = member_path(root, relative, label)
    require(path.is_dir(), f"missing required component {label}: {relative}")
    return path


def parse_hash_list(path: Path, label: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", raw)
        require(match is not None, f"{label} line {number} must be '<sha256><two spaces><relative path>'")
        digest, rel = match.groups()
        rel = canonical_relative_path(rel, f"{label} line {number} path")
        require(rel not in entries, f"{label} contains duplicate path: {rel}")
        entries[rel] = digest
    return entries


def actual_files_inventory(root: Path) -> dict[str, tuple[int, str]]:
    files_root = require_directory(root, FILES_ROOT_PATH, "Files snapshot")
    require(not (files_root / ".image-staging").exists(), "Files snapshot must exclude transient .image-staging")
    actual: dict[str, tuple[int, str]] = {}
    for path in sorted(files_root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ContractError(f"Files snapshot must not contain symbolic links: {path.relative_to(root).as_posix()}")
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            actual[rel] = (path.stat().st_size, sha256_file(path))
    return actual


def load_and_validate_inventory(root: Path) -> tuple[dict[str, tuple[int, str]], dict[str, Any]]:
    path = require_file(root, INVENTORY_PATH, "Files inventory")
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"Files inventory is not valid JSON: {path}") from exc
    require(isinstance(inventory, dict), "Files inventory must be a JSON object")
    require(inventory.get("schemaVersion") == 1, "Files inventory schemaVersion must be 1")
    require(inventory.get("root") == FILES_ROOT_PATH, "Files inventory root must be 'files'")
    declared_count = required_nonnegative_int(inventory.get("fileCount"), "Files inventory fileCount")
    declared_bytes = required_nonnegative_int(inventory.get("totalBytes"), "Files inventory totalBytes")
    entries = inventory.get("files")
    require(isinstance(entries, list), "Files inventory files must be an array")

    declared: dict[str, tuple[int, str]] = {}
    for index, item in enumerate(entries):
        require(isinstance(item, dict), f"Files inventory entry {index} must be an object")
        rel = canonical_relative_path(item.get("path"), f"Files inventory entry {index} path")
        require(rel.startswith("files/"), f"Files inventory entry {index} must be below files/")
        require(rel != "files/.image-staging" and not rel.startswith("files/.image-staging/"),
                "Files inventory must exclude transient .image-staging")
        require(rel not in declared, f"Files inventory contains duplicate path: {rel}")
        size = required_nonnegative_int(item.get("sizeBytes"), f"Files inventory entry {index} sizeBytes")
        digest = required_sha256(item.get("sha256"), f"Files inventory entry {index} sha256")
        declared[rel] = (size, digest)

    require(declared_count == len(declared), "Files inventory fileCount does not match its entries")
    require(declared_bytes == sum(size for size, _ in declared.values()), "Files inventory totalBytes does not match its entries")
    actual = actual_files_inventory(root)
    require(declared == actual, "Files inventory does not exactly match Files snapshot paths, sizes and hashes")
    return actual, inventory


def validate_database_hashes(root: Path, custom_sha: str, sql_sha: str) -> None:
    path = require_file(root, DATABASE_HASHES_PATH, "database SHA-256 list")
    entries = parse_hash_list(path, "database SHA-256 list")
    expected = {DATABASE_CUSTOM_PATH: custom_sha, DATABASE_SQL_PATH: sql_sha}
    require(entries == expected, "database.sha256 must contain exactly the custom and SQL dump hashes")


def validate_files_hashes(root: Path, inventory: dict[str, tuple[int, str]]) -> None:
    path = require_file(root, FILES_HASHES_PATH, "Files SHA-256 list")
    entries = parse_hash_list(path, "Files SHA-256 list")
    expected = {rel: digest for rel, (_size, digest) in inventory.items()}
    require(entries == expected, "files.sha256 must exactly match the durable Files inventory")


def validate_file_descriptor(root: Path, descriptor: Any, label: str, expected_path: str, expected_format: str) -> tuple[int, str]:
    require(isinstance(descriptor, dict), f"{label} descriptor must be an object")
    rel = canonical_relative_path(descriptor.get("path"), f"{label}.path")
    require(rel == expected_path, f"{label}.path must be {expected_path!r}")
    require(descriptor.get("format") == expected_format, f"{label}.format must be {expected_format!r}")
    size = required_positive_int(descriptor.get("sizeBytes"), f"{label}.sizeBytes")
    digest = required_sha256(descriptor.get("sha256"), f"{label}.sha256")
    require(descriptor.get("verification") == "verified", f"{label}.verification must be 'verified'")
    path = require_file(root, rel, label)
    require(path.stat().st_size == size, f"{label} size does not match manifest")
    require(sha256_file(path) == digest, f"{label} SHA-256 does not match manifest")
    return size, digest


def validate_hash_component(root: Path, descriptor: Any, label: str, expected_path: str) -> tuple[int, str]:
    require(isinstance(descriptor, dict), f"{label} descriptor must be an object")
    rel = canonical_relative_path(descriptor.get("path"), f"{label}.path")
    require(rel == expected_path, f"{label}.path must be {expected_path!r}")
    require(descriptor.get("format") == "sha256-list", f"{label}.format must be 'sha256-list'")
    size = required_positive_int(descriptor.get("sizeBytes"), f"{label}.sizeBytes")
    digest = required_sha256(descriptor.get("sha256"), f"{label}.sha256")
    require(descriptor.get("verification") == "verified", f"{label}.verification must be 'verified'")
    path = require_file(root, rel, label)
    require(path.stat().st_size == size, f"{label} size does not match manifest")
    require(sha256_file(path) == digest, f"{label} SHA-256 does not match manifest")
    return size, digest


def validate_manifest(root: Path, manifest: dict[str, Any], allow_partial_workspace: bool,
                      allow_fixed_working_root: bool = False) -> None:
    if allow_fixed_working_root:
        require(root.name == "diaries-backup", "fixed working root must be named diaries-backup")
        backup_id = required_string(manifest.get("backupId"), "backupId")
        parse_backup_id(backup_id)
        is_partial = False
    else:
        backup_id, is_partial = backup_id_from_directory(root)
    if is_partial:
        require(allow_partial_workspace,
                f"partial workspace {root.name!r} is non-restorable; use --allow-partial-workspace only during backup finalisation")

    schema = manifest.get("schemaVersion")
    require(isinstance(schema, int) and not isinstance(schema, bool), "schemaVersion must be an integer")
    require(schema in SUPPORTED_SCHEMA_VERSIONS,
            f"unsupported schemaVersion {schema!r}; supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    require(manifest.get("backupType") == "complete-dataset", "backupType must be 'complete-dataset'")
    require(manifest.get("completeDatasetBackup") is True, "completeDatasetBackup must be true")
    require(manifest.get("status") == "complete", "status must be 'complete'")
    require(manifest.get("backupId") == backup_id, "backupId must match the final/partial workspace directory name")

    started = parse_iso_timestamp(manifest.get("createdStartedAt"), "createdStartedAt")
    completed = parse_iso_timestamp(manifest.get("createdCompletedAt"), "createdCompletedAt")
    require(completed >= started, "createdCompletedAt must not precede createdStartedAt")

    dataset = required_string(manifest.get("logicalDataset"), "logicalDataset")
    require(DATASET_RE.fullmatch(dataset) is not None, "logicalDataset contains invalid characters")
    require(dataset not in (".", ".."), "logicalDataset is invalid")

    source = manifest.get("source")
    require(isinstance(source, dict), "source must be an object")
    required_string(source.get("launchMode"), "source.launchMode")
    consumers = source.get("knownConsumers")
    require(isinstance(consumers, list) and consumers and all(isinstance(item, str) and item.strip() for item in consumers),
            "source.knownConsumers must be a non-empty array of non-empty strings")
    identity = source.get("applicationIdentity")
    require(isinstance(identity, dict) and identity, "source.applicationIdentity must be a non-empty object")

    quiescence = manifest.get("writerQuiescence")
    require(isinstance(quiescence, dict), "writerQuiescence must be an object")
    require(quiescence.get("status") == "quiesced", "writerQuiescence.status must be 'quiesced'")
    required_string(quiescence.get("method"), "writerQuiescence.method")
    required_string(quiescence.get("evidence"), "writerQuiescence.evidence")
    writers = quiescence.get("writers")
    require(isinstance(writers, list) and writers and all(isinstance(item, str) and item.strip() for item in writers),
            "writerQuiescence.writers must be a non-empty array")

    staging = manifest.get("staging")
    require(isinstance(staging, dict), "staging must be an object")
    require(staging.get("relativePath") == ".image-staging", "staging.relativePath must be '.image-staging'")
    require(staging.get("disposition") in {"empty", "excluded-benign"},
            "staging.disposition must be 'empty' or 'excluded-benign'")
    staging_count = required_nonnegative_int(staging.get("entryCount"), "staging.entryCount")
    require(staging.get("snapshotIncluded") is False, "staging.snapshotIncluded must be false")
    required_string(staging.get("note"), "staging.note")
    if staging.get("disposition") == "empty":
        require(staging_count == 0, "staging.entryCount must be 0 when disposition is 'empty'")

    counts = manifest.get("counts")
    require(isinstance(counts, dict), "counts must be an object")
    required_nonnegative_int(counts.get("imageRowCount"), "counts.imageRowCount")
    required_nonnegative_int(counts.get("cataloguedFileCount"), "counts.cataloguedFileCount")
    durable_count = required_nonnegative_int(counts.get("durableFileCount"), "counts.durableFileCount")

    database = manifest.get("database")
    require(isinstance(database, dict), "database must be an object")
    required_string(database.get("storageIdentity"), "database.storageIdentity")
    required_string(database.get("name"), "database.name")
    _custom_size, custom_sha = validate_file_descriptor(root, database.get("customDump"), "database.customDump",
                                                        DATABASE_CUSTOM_PATH, "postgresql-custom")
    _sql_size, sql_sha = validate_file_descriptor(root, database.get("sqlDump"), "database.sqlDump",
                                                  DATABASE_SQL_PATH, "postgresql-plain-sql")

    files = manifest.get("files")
    require(isinstance(files, dict), "files must be an object")
    required_string(files.get("selector"), "files.selector")
    required_string(files.get("resolvedPhysicalRoot"), "files.resolvedPhysicalRoot")
    snapshot = files.get("snapshot")
    require(isinstance(snapshot, dict), "files.snapshot must be an object")
    snapshot_path = canonical_relative_path(snapshot.get("path"), "files.snapshot.path")
    require(snapshot_path == FILES_ROOT_PATH, "files.snapshot.path must be 'files'")
    require(snapshot.get("format") == "directory", "files.snapshot.format must be 'directory'")
    file_count = required_nonnegative_int(snapshot.get("fileCount"), "files.snapshot.fileCount")
    total_bytes = required_nonnegative_int(snapshot.get("totalBytes"), "files.snapshot.totalBytes")
    require(snapshot.get("verification") == "verified", "files.snapshot.verification must be 'verified'")
    inv_path = canonical_relative_path(snapshot.get("inventoryPath"), "files.snapshot.inventoryPath")
    require(inv_path == INVENTORY_PATH, f"files.snapshot.inventoryPath must be {INVENTORY_PATH!r}")
    required_sha256(snapshot.get("inventorySha256"), "files.snapshot.inventorySha256")
    hash_path = canonical_relative_path(snapshot.get("hashListPath"), "files.snapshot.hashListPath")
    require(hash_path == FILES_HASHES_PATH, f"files.snapshot.hashListPath must be {FILES_HASHES_PATH!r}")
    required_sha256(snapshot.get("hashListSha256"), "files.snapshot.hashListSha256")

    verification = manifest.get("verification")
    require(isinstance(verification, dict), "verification must be an object")
    validate_hash_component(root, verification.get("databaseHashList"), "verification.databaseHashList", DATABASE_HASHES_PATH)

    inventory, inventory_doc = load_and_validate_inventory(root)
    validate_database_hashes(root, custom_sha, sql_sha)
    validate_files_hashes(root, inventory)
    require(file_count == len(inventory), "files.snapshot.fileCount does not match inventory")
    require(total_bytes == sum(size for size, _digest in inventory.values()), "files.snapshot.totalBytes does not match inventory")
    require(durable_count == len(inventory), "counts.durableFileCount does not match durable Files inventory")
    require(snapshot.get("inventorySha256") == sha256_file(root / INVENTORY_PATH),
            "files.snapshot.inventorySha256 does not match inventory.json")
    require(snapshot.get("hashListSha256") == sha256_file(root / FILES_HASHES_PATH),
            "files.snapshot.hashListSha256 does not match files.sha256")
    require(inventory_doc.get("fileCount") == durable_count, "inventory fileCount does not match counts.durableFileCount")


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / MANIFEST_NAME
    require(path.is_file(), f"missing required manifest: {MANIFEST_NAME}")
    require(not path.is_symlink(), f"{MANIFEST_NAME} must not be a symbolic link")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"{MANIFEST_NAME} is not valid JSON") from exc
    require(isinstance(manifest, dict), f"{MANIFEST_NAME} must contain a JSON object")
    return manifest


def descriptor_for_file(root: Path, rel: str, format_name: str) -> dict[str, Any]:
    path = require_file(root, rel, rel)
    require(path.stat().st_size > 0, f"required component is empty: {rel}")
    return {
        "path": rel,
        "format": format_name,
        "sizeBytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "verification": "verified",
    }


def parse_application_identity(text: str | None, encoded: str | None) -> dict[str, Any]:
    require((text is None) != (encoded is None),
            "exactly one application identity representation must be supplied")
    if encoded is not None:
        try:
            text = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ContractError("--application-identity-base64 must contain Base64-encoded UTF-8 JSON") from exc
    assert text is not None
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError("application identity must be valid JSON") from exc
    require(isinstance(value, dict) and value, "application identity must contain a non-empty object")
    return value


def command_write(args: argparse.Namespace) -> int:
    root = Path(args.backup_dir).resolve()
    require(root.is_dir(), f"backup workspace does not exist: {root}")
    if args.fixed_backup_id:
        require(root.name == 'diaries-backup', 'fixed manifest write requires diaries-backup directory')
        backup_id = args.fixed_backup_id
        parse_backup_id(backup_id)
    else:
        backup_id, _is_partial = backup_id_from_directory(root)
    require(DATASET_RE.fullmatch(args.logical_dataset) is not None, "--logical-dataset contains invalid characters")
    require(args.logical_dataset not in (".", ".."), "--logical-dataset is invalid")

    # A write is only allowed after the Step-2 required verification artifacts already exist and are coherent.
    custom = descriptor_for_file(root, DATABASE_CUSTOM_PATH, "postgresql-custom")
    sql = descriptor_for_file(root, DATABASE_SQL_PATH, "postgresql-plain-sql")
    inventory, _inventory_doc = load_and_validate_inventory(root)
    validate_database_hashes(root, custom["sha256"], sql["sha256"])
    validate_files_hashes(root, inventory)
    db_hash_descriptor = descriptor_for_file(root, DATABASE_HASHES_PATH, "sha256-list")
    files_hash_path = require_file(root, FILES_HASHES_PATH, "Files SHA-256 list")
    inventory_path = require_file(root, INVENTORY_PATH, "Files inventory")

    started = args.started_at or dt.datetime.now(dt.timezone.utc).isoformat()
    completed = args.completed_at or dt.datetime.now(dt.timezone.utc).isoformat()
    started_parsed = parse_iso_timestamp(started, "--started-at")
    completed_parsed = parse_iso_timestamp(completed, "--completed-at")
    require(completed_parsed >= started_parsed, "--completed-at must not precede --started-at")

    consumers = args.known_consumer or [args.launch_mode]
    writers = args.writer or []
    require(writers, "at least one --writer must be supplied")
    staging_count = int(args.staging_entry_count)
    if args.staging_disposition == "empty":
        require(staging_count == 0, "--staging-entry-count must be 0 when --staging-disposition=empty")

    manifest: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "backupType": "complete-dataset",
        "completeDatasetBackup": True,
        "status": "complete",
        "backupId": backup_id,
        "createdStartedAt": started,
        "createdCompletedAt": completed,
        "logicalDataset": args.logical_dataset,
        "source": {
            "launchMode": args.launch_mode,
            "knownConsumers": consumers,
            "applicationIdentity": parse_application_identity(args.application_identity_json, args.application_identity_base64),
        },
        "writerQuiescence": {
            "status": "quiesced",
            "method": args.writer_method,
            "writers": writers,
            "evidence": args.writer_evidence,
        },
        "staging": {
            "relativePath": ".image-staging",
            "disposition": args.staging_disposition,
            "entryCount": staging_count,
            "snapshotIncluded": False,
            "note": args.staging_note,
        },
        "counts": {
            "imageRowCount": int(args.image_row_count),
            "cataloguedFileCount": int(args.catalogued_file_count),
            "durableFileCount": len(inventory),
        },
        "database": {
            "storageIdentity": args.database_storage_identity,
            "name": args.database_name,
            "customDump": custom,
            "sqlDump": sql,
        },
        "files": {
            "selector": args.files_selector,
            "resolvedPhysicalRoot": args.files_root,
            "snapshot": {
                "path": FILES_ROOT_PATH,
                "format": "directory",
                "fileCount": len(inventory),
                "totalBytes": sum(size for size, _digest in inventory.values()),
                "inventoryPath": INVENTORY_PATH,
                "inventorySha256": sha256_file(inventory_path),
                "hashListPath": FILES_HASHES_PATH,
                "hashListSha256": sha256_file(files_hash_path),
                "verification": "verified",
            },
        },
        "verification": {
            "databaseHashList": db_hash_descriptor,
        },
    }

    manifest_path = root / MANIFEST_NAME
    if manifest_path.exists() and not args.force:
        raise ContractError(f"manifest already exists: {manifest_path}; use --force only when deliberately regenerating a candidate")
    temporary = root / f".{MANIFEST_NAME}.tmp"
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, manifest_path)
    try:
        validate_manifest(root, manifest, allow_partial_workspace=True, allow_fixed_working_root=bool(args.fixed_backup_id))
    except Exception:
        try:
            manifest_path.unlink()
        except OSError:
            pass
        raise
    print(manifest_path)
    return 0


def command_verify(args: argparse.Namespace) -> int:
    root = Path(args.backup_dir).resolve()
    require(root.is_dir(), f"backup directory does not exist: {root}")
    manifest = load_manifest(root)
    validate_manifest(root, manifest, allow_partial_workspace=args.allow_partial_workspace,
                      allow_fixed_working_root=args.allow_fixed_working_root)
    backup_id, is_partial = (manifest["backupId"], False) if args.allow_fixed_working_root else backup_id_from_directory(root)
    print("Valid complete Diaries dataset backup manifest")
    print(f"  Schema:          {SCHEMA_VERSION}")
    print(f"  Backup ID:       {backup_id}")
    print(f"  Logical dataset: {manifest['logicalDataset']}")
    print(f"  Workspace:       {'partial candidate' if is_partial else 'completed backup'}")
    print(f"  Files:           {manifest['counts']['durableFileCount']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("write", help="write schema-2 dataset-manifest.json for an already verified candidate workspace")
    p.add_argument("--backup-dir", required=True)
    p.add_argument("--logical-dataset", required=True)
    p.add_argument("--launch-mode", required=True)
    p.add_argument("--known-consumer", action="append", default=[])
    p.add_argument("--database-storage-identity", required=True)
    p.add_argument("--database-name", required=True)
    p.add_argument("--files-selector", required=True)
    p.add_argument("--files-root", required=True)
    identity_group = p.add_mutually_exclusive_group(required=True)
    identity_group.add_argument("--application-identity-json",
                                help="application identity as JSON; retained for direct/scripted callers")
    identity_group.add_argument("--application-identity-base64",
                                help="application identity as Base64-encoded UTF-8 JSON; safe for Windows native argv")
    p.add_argument("--writer-method", required=True)
    p.add_argument("--writer", action="append", default=[])
    p.add_argument("--writer-evidence", required=True)
    p.add_argument("--image-row-count", type=int, required=True)
    p.add_argument("--catalogued-file-count", type=int, required=True)
    p.add_argument("--staging-disposition", choices=("empty", "excluded-benign"), required=True)
    p.add_argument("--staging-entry-count", type=int, required=True)
    p.add_argument("--staging-note", required=True)
    p.add_argument("--started-at")
    p.add_argument("--completed-at")
    p.add_argument("--force", action="store_true")
    p.add_argument("--fixed-backup-id", help="0036: explicit UTC backup ID when writing fixed diaries-backup root")
    p.set_defaults(func=command_write)

    p = sub.add_parser("verify", help="validate a complete dataset backup directory and every Step-2 required component")
    p.add_argument("--backup-dir", required=True)
    p.add_argument("--allow-fixed-working-root", action="store_true",
                   help="verify a mutable working dataset named diaries-backup against its manifest backupId")
    p.add_argument("--allow-partial-workspace", action="store_true",
                   help="permit .<backup-id>.partial only while finalising a candidate; normal restore selection must not use this")
    p.set_defaults(func=command_verify)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        # argparse int accepts negatives; reject them consistently here before generation.
        for field in ("image_row_count", "catalogued_file_count", "staging_entry_count"):
            if hasattr(args, field):
                require(getattr(args, field) >= 0, f"--{field.replace('_', '-')} must be non-negative")
        return args.func(args)
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
