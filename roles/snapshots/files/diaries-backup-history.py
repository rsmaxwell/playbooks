#!/usr/bin/python3
"""Read-only history view over verified Diaries datasets in managed Btrfs snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

TIMESTAMP_RE = re.compile(r"^\d{8}-\d{6}Z$")


class HistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoryConfig:
    snapshot_root: Path
    source_name: str
    dataset_relative_path: str
    marker_relative_path: str
    manifest_tool: Path


@dataclass(frozen=True)
class Occurrence:
    snapshot: str
    snapshot_root: Path
    dataset_path: Path
    logical_dataset: str
    backup_id: str
    manifest_sha256: str


def safe_relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise HistoryError(f"{field} must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or "\\" in value or any(part in ("", ".", "..") for part in path.parts):
        raise HistoryError(f"{field} must be a canonical relative path")
    if path.as_posix() != value:
        raise HistoryError(f"{field} must be a canonical relative path")
    return value


def load_config(path: Path) -> HistoryConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HistoryError(f"cannot read configuration {path}: {exc}") from exc
    verification = raw.get("verification", {})
    if not verification.get("required", False):
        raise HistoryError("Diaries verification is not enabled in snapshot-manager configuration")
    source_name = str(verification.get("source_name", ""))
    sources = {str(item.get("name")): Path(item.get("path", "")) for item in raw.get("sources", [])}
    if source_name not in sources:
        raise HistoryError("verification.source_name is not a configured snapshot source")
    manifest_tool = Path(verification.get("manifest_tool") or "")
    if not manifest_tool.is_absolute():
        raise HistoryError("verification.manifest_tool must be configured as an absolute path")
    return HistoryConfig(
        snapshot_root=Path(raw["snapshot_root"]).resolve(),
        source_name=source_name,
        dataset_relative_path=safe_relative(verification.get("dataset_relative_path"), "verification.dataset_relative_path"),
        marker_relative_path=safe_relative(verification.get("marker_relative_path"), "verification.marker_relative_path"),
        manifest_tool=manifest_tool,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def joined(root: Path, relative: str) -> Path:
    return root.joinpath(*PurePosixPath(relative).parts)


def resolved_inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise HistoryError(f"{label} escapes snapshot occurrence {root_resolved}: {resolved}") from exc
    return resolved


def inspect_occurrence(config: HistoryConfig, snapshot: str) -> Occurrence:
    occurrence_root = config.snapshot_root / config.source_name / snapshot
    if not occurrence_root.is_dir() or occurrence_root.is_symlink():
        raise HistoryError(f"managed snapshot occurrence missing/unsafe: {occurrence_root}")
    marker_path = joined(occurrence_root, config.marker_relative_path)
    if marker_path.is_symlink() or not marker_path.is_file():
        raise HistoryError("verified marker missing/unsafe")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryError(f"cannot parse verified marker: {exc}") from exc
    if not isinstance(marker, dict):
        raise HistoryError("verified marker is not a JSON object")
    if marker.get("state") != "verified-published" or marker.get("snapshotEligible") is not True:
        raise HistoryError("snapshot marker is not verified/snapshot eligible")
    if marker.get("datasetRelativePath") != config.dataset_relative_path:
        raise HistoryError("snapshot marker datasetRelativePath conflicts with configuration")

    dataset_lexical = joined(occurrence_root, config.dataset_relative_path)
    dataset_path = resolved_inside(dataset_lexical, occurrence_root, "Diaries dataset")
    manifest_path = dataset_path / "dataset-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise HistoryError("dataset manifest missing/unsafe")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoryError(f"cannot parse dataset manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise HistoryError("dataset manifest is not a JSON object")
    backup_id = manifest.get("backupId")
    logical_dataset = manifest.get("logicalDataset")
    if not isinstance(backup_id, str) or not backup_id:
        raise HistoryError("dataset manifest has no valid backupId")
    if not isinstance(logical_dataset, str) or not logical_dataset:
        raise HistoryError("dataset manifest has no valid logicalDataset")
    if marker.get("backupId") != backup_id or marker.get("logicalDataset") != logical_dataset:
        raise HistoryError("snapshot marker identity conflicts with dataset manifest")
    actual_hash = sha256_file(manifest_path)
    if marker.get("manifestSha256") != actual_hash:
        raise HistoryError("snapshot marker manifestSha256 conflicts with dataset manifest")
    return Occurrence(
        snapshot=snapshot,
        snapshot_root=occurrence_root,
        dataset_path=dataset_path,
        logical_dataset=logical_dataset,
        backup_id=backup_id,
        manifest_sha256=actual_hash,
    )


def enumerate_occurrences(config: HistoryConfig) -> tuple[list[Occurrence], list[tuple[str, str]]]:
    source_root = config.snapshot_root / config.source_name
    if not source_root.is_dir():
        raise HistoryError(f"managed snapshot source directory missing: {source_root}")
    occurrences: list[Occurrence] = []
    warnings: list[tuple[str, str]] = []
    names = sorted(
        (item.name for item in source_root.iterdir() if item.is_dir() and TIMESTAMP_RE.fullmatch(item.name)),
    )
    for name in names:
        try:
            occurrences.append(inspect_occurrence(config, name))
        except (HistoryError, OSError) as exc:
            warnings.append((name, str(exc)))
    return occurrences, warnings


def group_occurrences(occurrences: Iterable[Occurrence]) -> dict[tuple[str, str], list[Occurrence]]:
    grouped: dict[tuple[str, str], list[Occurrence]] = {}
    for occurrence in occurrences:
        grouped.setdefault((occurrence.logical_dataset, occurrence.backup_id), []).append(occurrence)
    for values in grouped.values():
        values.sort(key=lambda item: item.snapshot)
    return grouped


def conflicted_groups(grouped: dict[tuple[str, str], list[Occurrence]]) -> set[tuple[str, str]]:
    conflicts: set[tuple[str, str]] = set()
    for key, values in grouped.items():
        if len({item.manifest_sha256 for item in values}) > 1:
            conflicts.add(key)
    return conflicts


def emit_warnings(warnings: list[tuple[str, str]]) -> None:
    for snapshot, message in warnings:
        print(f"WARNING {snapshot}: {message}", file=sys.stderr)


def select_backup(
    grouped: dict[tuple[str, str], list[Occurrence]], backup_id: str, logical_dataset: str | None
) -> tuple[tuple[str, str], list[Occurrence]]:
    matches = [(key, values) for key, values in grouped.items() if key[1] == backup_id]
    if logical_dataset is not None:
        matches = [(key, values) for key, values in matches if key[0] == logical_dataset]
    if not matches:
        raise HistoryError(f"backup ID not found in retained verified snapshots: {backup_id}")
    if len(matches) != 1:
        datasets = ", ".join(sorted(key[0] for key, _ in matches))
        raise HistoryError(f"backup ID occurs in multiple logical datasets ({datasets}); specify --logical-dataset")
    return matches[0]


def inspect_published(published_root: Path) -> Occurrence:
    """Inspect a fixed published schema-2 backup; never discover fabricated ext4 snapshots."""
    if published_root.is_symlink():
        # The production publication is an atomic symlink to a generation.
        dataset = published_root.resolve(strict=True)
        if dataset.parent.name != ".diaries-backup-generations" or dataset.parent.parent != published_root.parent.resolve():
            raise HistoryError("published symlink does not point to a local generation")
    else:
        dataset = published_root.resolve(strict=True)
    if not dataset.is_dir():
        raise HistoryError("published dataset is not a directory")
    manifest = dataset / "dataset-manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise HistoryError("published dataset manifest missing/unsafe")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HistoryError(f"cannot parse published dataset manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("schemaVersion") != 2:
        raise HistoryError("published dataset is not schema-2")
    backup_id, logical_dataset = data.get("backupId"), data.get("logicalDataset")
    if not isinstance(backup_id, str) or not backup_id or not isinstance(logical_dataset, str) or not logical_dataset:
        raise HistoryError("published dataset has invalid identity")
    return Occurrence("live", published_root.parent, dataset, logical_dataset, backup_id, sha256_file(manifest))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="/etc/btrfs-snapshot-manager.json")
    parser.add_argument("--published-root", type=Path, help="fixed live schema-2 publication (pluto mode); no Btrfs history implied")
    parser.add_argument("--manifest-tool", type=Path, help="schema-2 verifier for published mode")
    parser.add_argument("--json", action="store_true", dest="json_output")
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list")
    list_parser.add_argument("--all", action="store_true")
    for name in ("show", "path", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("backup_id")
        cmd.add_argument("--logical-dataset")
        cmd.add_argument("--snapshot")
    args = parser.parse_args(argv)

    try:
        if args.published_root:
            config = None
            occurrences = [inspect_published(args.published_root)]
            warnings = []
        else:
            config = load_config(Path(args.config))
            occurrences, warnings = enumerate_occurrences(config)
        grouped = group_occurrences(occurrences)
        conflicts = conflicted_groups(grouped)
        emit_warnings(warnings)

        if args.command == "list":
            if args.all:
                rows = []
                for occurrence in sorted(occurrences, key=lambda item: item.snapshot):
                    conflict = (occurrence.logical_dataset, occurrence.backup_id) in conflicts
                    rows.append({
                        "logicalDataset": occurrence.logical_dataset,
                        "backupId": occurrence.backup_id,
                        "snapshot": occurrence.snapshot,
                        "path": str(occurrence.dataset_path),
                        "status": "conflict" if conflict else "verified",
                    })
                if args.json_output:
                    print(json.dumps({"occurrences": rows, "warnings": warnings}, sort_keys=True))
                else:
                    print("LOGICAL DATASET  BACKUP ID          SNAPSHOT             STATUS")
                    for row in rows:
                        print(f"{row['logicalDataset']:<16} {row['backupId']:<18} {row['snapshot']:<20} {row['status']}")
                return 2 if conflicts or warnings else 0

            rows = []
            for key in sorted(grouped):
                values = grouped[key]
                rows.append({
                    "logicalDataset": key[0],
                    "backupId": key[1],
                    "firstRetainedSnapshot": values[0].snapshot,
                    "lastRetainedSnapshot": values[-1].snapshot,
                    "snapshots": len(values),
                    "status": "conflict" if key in conflicts else "verified",
                })
            if args.json_output:
                print(json.dumps({"backups": rows, "warnings": warnings}, sort_keys=True))
            else:
                print("LOGICAL DATASET  BACKUP ID          FIRST RETAINED        LAST RETAINED         SNAPSHOTS STATUS")
                for row in rows:
                    print(
                        f"{row['logicalDataset']:<16} {row['backupId']:<18} "
                        f"{row['firstRetainedSnapshot']:<21} {row['lastRetainedSnapshot']:<21} "
                        f"{row['snapshots']:<9} {row['status']}"
                    )
            return 2 if conflicts or warnings else 0

        key, values = select_backup(grouped, args.backup_id, args.logical_dataset)
        if key in conflicts:
            raise HistoryError("selected backup ID has conflicting retained manifest identities")
        if args.snapshot:
            selected = [item for item in values if item.snapshot == args.snapshot]
            if not selected:
                raise HistoryError(f"backup ID is not present in requested snapshot: {args.snapshot}")
            values = selected

        if args.command == "show":
            rows = [
                {"snapshot": item.snapshot, "path": str(item.dataset_path), "manifestSha256": item.manifest_sha256}
                for item in values
            ]
            if args.json_output:
                print(json.dumps({"logicalDataset": key[0], "backupId": key[1], "occurrences": rows}, sort_keys=True))
            else:
                print(f"logicalDataset={key[0]}")
                print(f"backupId={key[1]}")
                for row in rows:
                    print(f"snapshot={row['snapshot']};path={row['path']};manifestSha256={row['manifestSha256']}")
            return 0

        occurrence = values[0]
        if args.command == "path":
            print(occurrence.dataset_path)
            return 0

        if args.command == "verify":
            verifier = (args.manifest_tool if config is None else config.manifest_tool)
            if verifier is None or not verifier.is_file():
                raise HistoryError(f"schema-2 verifier missing: {verifier}")
            result = subprocess.run(
                [sys.executable, str(verifier), "verify", "--backup-dir", str(occurrence.dataset_path)],
                text=True,
            )
            if result.returncode != 0:
                raise HistoryError(f"schema-2 verification failed for {occurrence.dataset_path}")
            print(
                f"VERIFIED logicalDataset={key[0]} backupId={key[1]} "
                f"snapshot={occurrence.snapshot} path={occurrence.dataset_path}"
            )
            return 0
        raise AssertionError(args.command)
    except (HistoryError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
