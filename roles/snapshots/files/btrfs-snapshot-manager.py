#!/usr/bin/python3
"""Small timestamp-named Btrfs snapshot manager.

The manager owns only snapshots below the configured snapshot_root. It never
reads, renames or deletes legacy numeric .snapshots/<number> trees.

For Diaries-integrated backup hosts, create is additionally guarded by a
receiver-written verification marker and a shared writer lock. A snapshot can
therefore never be created while a managed receive is mutating the mirror, and
an unverified/mismatched Diaries mirror is rejected before snapshot creation.
"""

from __future__ import annotations

import argparse
import dataclasses
import csv
import io
import fcntl
import hashlib
import json
import os
import socket
import stat
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

TIMESTAMP_FORMAT = "%Y%m%d-%H%M%SZ"
TIMESTAMP_RE = re.compile(r"^\d{8}-\d{6}Z$")


class SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class SnapshotSource:
    name: str
    source: Path | None
    snapshot_directory: Path | None = None
    required: bool = True
    creation: bool = True
    prune: bool = True


@dataclass(frozen=True)
class RetentionPolicy:
    hourly: int
    daily: int
    weekly: int
    monthly: int
    yearly: int
    minimum_age_minutes: int


@dataclass(frozen=True)
class VerificationPolicy:
    required: bool
    source_name: str
    dataset_relative_path: str
    marker_relative_path: str
    manifest_tool: Path | None


@dataclass(frozen=True)
class Config:
    snapshot_root: Path
    lock_path: Path
    writer_lock_path: Path | None
    sources: tuple[SnapshotSource, ...]
    retention: RetentionPolicy
    verification: VerificationPolicy
    replication_protection_required: bool = False
    replication_protection_file: Path | None = None
    checkpoint_holds_file: Path | None = None
    checkpoint_holds_required: bool = False
    mode: str = "source"
    receiver_state_dir: Path | None = None
    receiver_prune_enabled: bool = False
    required_snapshot_sources: tuple[str, ...] = ()
    creation_source_names: tuple[str, ...] = ()
    prune_source_names: tuple[str, ...] = ()


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode != 0:
        raise SnapshotError(
            "command failed (rc={}): {}\nstdout:\n{}\nstderr:\n{}".format(
                result.returncode,
                " ".join(command),
                result.stdout.rstrip(),
                result.stderr.rstrip(),
            )
        )
    return result


def positive_int(value: object, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise SnapshotError(f"{field} must be an integer") from exc
    if number < 0:
        raise SnapshotError(f"{field} must not be negative")
    return number


def safe_relative(value: object, field: str, *, allow_empty: bool = False) -> str:
    if value in (None, "") and allow_empty:
        return ""
    if not isinstance(value, str) or not value:
        raise SnapshotError(f"{field} must be a non-empty relative path")
    if "\\" in value:
        raise SnapshotError(f"{field} must use '/' separators")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise SnapshotError(f"{field} must be a canonical relative path")
    canonical = path.as_posix()
    if canonical != value:
        raise SnapshotError(f"{field} must be a canonical relative path")
    return canonical


def load_config(path: Path) -> Config:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SnapshotError(f"cannot read configuration {path}: {exc}") from exc

    mode = raw.get("mode", "source")
    if mode not in ("source", "receiver"):
        raise SnapshotError("mode must be source or receiver")
    receiver_state_raw = raw.get("receiver_state_dir")
    if mode == "receiver" and (not isinstance(receiver_state_raw, str) or not Path(receiver_state_raw).is_absolute()):
        raise SnapshotError("receiver mode requires absolute receiver_state_dir")
    root = Path(raw["snapshot_root"]).resolve()
    lock_path = Path(raw.get("lock_path", "/run/lock/btrfs-snapshot-manager.lock"))
    writer_lock_raw = raw.get("writer_lock_path") or ""
    writer_lock_path = Path(writer_lock_raw) if writer_lock_raw else None
    if writer_lock_path is not None and not writer_lock_path.is_absolute():
        raise SnapshotError("writer_lock_path must be absolute when configured")

    sources: list[SnapshotSource] = []
    seen_names: set[str] = set()
    for item in raw.get("sources", []):
        name = str(item["name"])
        if not name or "/" in name or name in {".", ".."}:
            raise SnapshotError(f"invalid snapshot source name: {name!r}")
        if name in seen_names:
            raise SnapshotError(f"duplicate snapshot source name: {name}")
        seen_names.add(name)
        path_raw = item.get("path")
        if mode == "source" and (not isinstance(path_raw, str) or not Path(path_raw).is_absolute()):
            raise SnapshotError("source mode requires an absolute source path")
        directory_raw = item.get("snapshot_directory")
        if directory_raw is not None and (not isinstance(directory_raw, str) or not Path(directory_raw).is_absolute()):
            raise SnapshotError("snapshot_directory must be absolute")
        if mode == "receiver" and directory_raw is None:
            raise SnapshotError("receiver mode requires explicit snapshot_directory")
        for flag in ("required", "creation", "prune"):
            if flag in item and type(item[flag]) is not bool:
                raise SnapshotError(f"source {name} {flag} must be a boolean")
        sources.append(SnapshotSource(
            name=name,
            source=Path(path_raw).resolve() if path_raw else None,
            snapshot_directory=Path(directory_raw).resolve() if directory_raw else None,
            required=item.get("required", True),
            creation=item.get("creation", True),
            prune=item.get("prune", True),
        ))

    if not sources:
        raise SnapshotError("configuration has no snapshot sources")
    # Transitional compatibility with installed JSON configurations using the
    # earlier selection lists. Never allow competing source flags and lists.
    legacy = ("required_snapshot_sources", "creation_source_names", "prune_source_names")
    if any(key in raw for key in legacy):
        if any(any(flag in item for flag in ("required", "creation", "prune")) for item in raw["sources"]):
            raise SnapshotError("cannot combine legacy source lists with per-source flags")
        def legacy_names(key: str) -> tuple[str, ...]:
            value = raw.get(key)
            if value is None:
                return tuple(item.name for item in sources)
            if not isinstance(value, list) or not value or any(type(n) is not str for n in value):
                raise SnapshotError(f"{key} must be a nonempty list")
            if len(set(value)) != len(value) or not set(value).issubset(seen_names):
                raise SnapshotError(f"{key} has duplicate or unknown sources")
            return tuple(value)
        required_names = legacy_names(legacy[0])
        creation_names = legacy_names(legacy[1])
        prune_names = legacy_names(legacy[2])
        sources = [dataclasses.replace(source,
                    required=source.name in required_names,
                    creation=source.name in creation_names,
                    prune=source.name in prune_names) for source in sources]
    else:
        required_names = tuple(source.name for source in sources if source.required)
        creation_names = tuple(source.name for source in sources if source.creation)
        prune_names = tuple(source.name for source in sources if source.prune)
    if mode == "source":
        if not required_names or not creation_names or not prune_names:
            raise SnapshotError("source mode requires required, creation and prune sources")
        if not set(required_names).issubset(creation_names):
            raise SnapshotError("all required sources must enable creation")
    if mode == "receiver" and len(sources) != 1:
        raise SnapshotError("receiver mode requires exactly one snapshot collection")

    retention = raw.get("retention", {})
    policy = RetentionPolicy(
        hourly=positive_int(retention.get("hourly", 0), "retention.hourly"),
        daily=positive_int(retention.get("daily", 0), "retention.daily"),
        weekly=positive_int(retention.get("weekly", 0), "retention.weekly"),
        monthly=positive_int(retention.get("monthly", 0), "retention.monthly"),
        yearly=positive_int(retention.get("yearly", 0), "retention.yearly"),
        minimum_age_minutes=positive_int(
            retention.get("minimum_age_minutes", 30), "retention.minimum_age_minutes"
        ),
    )

    verification_raw = raw.get("verification", {})
    required = bool(verification_raw.get("required", False))
    source_name = str(verification_raw.get("source_name", ""))
    dataset_relative_path = safe_relative(
        verification_raw.get("dataset_relative_path", ""),
        "verification.dataset_relative_path",
        allow_empty=not required,
    )
    marker_relative_path = safe_relative(
        verification_raw.get("marker_relative_path", ""),
        "verification.marker_relative_path",
        allow_empty=not required,
    )
    manifest_tool_raw = verification_raw.get("manifest_tool") or ""
    manifest_tool = Path(manifest_tool_raw) if manifest_tool_raw else None
    if manifest_tool is not None and not manifest_tool.is_absolute():
        raise SnapshotError("verification.manifest_tool must be absolute when configured")
    if required:
        if mode == "receiver":
            raise SnapshotError("Diaries source verification is not permitted in receiver mode")
        if source_name not in seen_names:
            raise SnapshotError("verification.source_name must name a configured snapshot source")
        if writer_lock_path is None:
            raise SnapshotError("writer_lock_path is required when Diaries verification is required")

    verification = VerificationPolicy(
        required=required,
        source_name=source_name,
        dataset_relative_path=dataset_relative_path,
        marker_relative_path=marker_relative_path,
        manifest_tool=manifest_tool,
    )
    return Config(
        snapshot_root=root,
        lock_path=lock_path,
        writer_lock_path=writer_lock_path,
        sources=tuple(sources),
        retention=policy,
        verification=verification,
        replication_protection_required=bool(raw.get("replication_protection", {}).get("required", False)),
        replication_protection_file=Path(raw.get("replication_protection", {}).get("path", str(root / ".replication-protection.json"))),
        checkpoint_holds_file=Path(raw.get("checkpoint_holds", {}).get("path", str(root / ".checkpoint-holds.json"))),
        checkpoint_holds_required=bool(raw.get("checkpoint_holds", {}).get("required", False)),
        mode=mode,
        receiver_state_dir=Path(receiver_state_raw).resolve() if receiver_state_raw else None,
        receiver_prune_enabled=raw.get("receiver_prune_enabled") is True,
        required_snapshot_sources=required_names,
        creation_source_names=creation_names,
        prune_source_names=prune_names,
    )


def require_root() -> None:
    if os.geteuid() != 0:
        raise SnapshotError("this command must run as root")


def filesystem_type(path: Path) -> str:
    result = run(["findmnt", "-T", str(path), "-n", "-o", "FSTYPE"])
    value = result.stdout.strip()
    if not value:
        raise SnapshotError(f"could not determine filesystem type for {path}")
    return value


def require_btrfs(path: Path) -> None:
    fstype = filesystem_type(path)
    if fstype != "btrfs":
        raise SnapshotError(f"{path} is on {fstype}, expected btrfs")


def require_subvolume(path: Path) -> None:
    result = run(["btrfs", "subvolume", "show", str(path)], check=False)
    if result.returncode != 0:
        raise SnapshotError(f"{path} is not an accessible Btrfs subvolume")


def source_directory(config: Config, source: SnapshotSource) -> Path:
    return source.snapshot_directory or (config.snapshot_root / source.name)


def snapshot_path(config: Config, source: SnapshotSource, timestamp: str) -> Path:
    return source_directory(config, source) / timestamp


def source_by_name(config: Config, name: str) -> SnapshotSource:
    for source in config.sources:
        if source.name == name:
            return source
    raise SnapshotError(f"configured snapshot source not found: {name}")


def path_within(root: Path, relative: str) -> Path:
    return root.joinpath(*PurePosixPath(relative).parts)


def resolved_inside(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    root_resolved = root.resolve(strict=True)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise SnapshotError(f"{label} escapes managed source {root_resolved}: {resolved}") from exc
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_verified_diaries(config: Config, *, strict: bool) -> dict[str, object] | None:
    verification = config.verification
    if not verification.required:
        return None
    source = source_by_name(config, verification.source_name)
    marker_path = path_within(source.source, verification.marker_relative_path)
    dataset_path = path_within(source.source, verification.dataset_relative_path)
    try:
        if marker_path.is_symlink() or not marker_path.is_file():
            raise SnapshotError(f"verified Diaries marker missing/unsafe: {marker_path}")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if not isinstance(marker, dict):
            raise SnapshotError("verified Diaries marker must be a JSON object")
        if marker.get("state") != "verified-published" or marker.get("snapshotEligible") is not True:
            raise SnapshotError("Diaries marker is not snapshot eligible")
        if marker.get("datasetRelativePath") != verification.dataset_relative_path:
            raise SnapshotError("Diaries marker datasetRelativePath does not match manager configuration")
        backup_id = marker.get("backupId")
        logical_dataset = marker.get("logicalDataset")
        manifest_hash = marker.get("manifestSha256")
        if not isinstance(backup_id, str) or not backup_id:
            raise SnapshotError("Diaries marker has no valid backupId")
        if not isinstance(logical_dataset, str) or not logical_dataset:
            raise SnapshotError("Diaries marker has no valid logicalDataset")
        if not isinstance(manifest_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", manifest_hash):
            raise SnapshotError("Diaries marker has no valid manifestSha256")

        resolved_dataset = resolved_inside(dataset_path, source.source, "Diaries dataset")
        manifest_path = resolved_dataset / "dataset-manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise SnapshotError(f"Diaries manifest missing/unsafe: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise SnapshotError("Diaries manifest must be a JSON object")
        if manifest.get("backupId") != backup_id or manifest.get("logicalDataset") != logical_dataset:
            raise SnapshotError("Diaries marker identity does not match current manifest")
        actual_hash = sha256_file(manifest_path)
        if actual_hash != manifest_hash:
            raise SnapshotError("Diaries marker manifestSha256 does not match current manifest")
        return {
            "backupId": backup_id,
            "logicalDataset": logical_dataset,
            "manifestSha256": actual_hash,
            "marker": str(marker_path),
            "dataset": str(dataset_path),
        }
    except (OSError, ValueError, json.JSONDecodeError, SnapshotError) as exc:
        if strict:
            if isinstance(exc, SnapshotError):
                raise
            raise SnapshotError(f"cannot validate verified Diaries state: {exc}") from exc
        return {"error": str(exc)}


def preflight(config: Config) -> None:
    if (not config.snapshot_root.is_dir() or config.snapshot_root.is_symlink()):
        raise SnapshotError(f"snapshot root missing or unsafe: {config.snapshot_root}")
    require_btrfs(config.snapshot_root)
    # The source repository must be a subvolume. The receiver repository is
    # an ordinary directory containing received subvolumes; never require the
    # enclosing directory itself to be a subvolume.
    if config.mode == "source":
        require_subvolume(config.snapshot_root)

    root_device = run(["findmnt", "-T", str(config.snapshot_root), "-n", "-o", "UUID"]).stdout.strip()
    if not root_device:
        raise SnapshotError(f"could not determine Btrfs filesystem UUID for {config.snapshot_root}")
    for source in config.sources:
        directory = source_directory(config, source)
        if not directory.is_dir() or directory.is_symlink():
            raise SnapshotError(f"unsafe snapshot directory: {directory}")
        require_btrfs(directory)
        directory_device = run(["findmnt", "-T", str(directory), "-n", "-o", "UUID"]).stdout.strip()
        if directory_device != root_device:
            raise SnapshotError(f"snapshot directory is on a different filesystem: {directory}")
        if config.mode == "receiver":
            continue
        if source.source is None or not source.source.exists():
            raise SnapshotError(f"snapshot source does not exist: {source.source}")
        require_btrfs(source.source)
        require_subvolume(source.source)
        source_device = run(["findmnt", "-T", str(source.source), "-n", "-o", "UUID"]).stdout.strip()
        if not source_device:
            raise SnapshotError(f"could not determine Btrfs filesystem UUID for {source.source}")
        if source_device != root_device:
            raise SnapshotError(
                f"snapshot source {source.source} and repository {config.snapshot_root} "
                f"are not on the same Btrfs filesystem ({source_device!r} != {root_device!r})"
            )

    if config.verification.required:
        source = source_by_name(config, config.verification.source_name)
        dataset_parent = path_within(source.source, config.verification.dataset_relative_path).parent
        marker_parent = path_within(source.source, config.verification.marker_relative_path).parent
        for label, parent in (("dataset", dataset_parent), ("marker", marker_parent)):
            if not parent.exists() or not parent.is_dir() or parent.is_symlink():
                raise SnapshotError(f"verified Diaries {label} parent missing/unsafe: {parent}")
        if config.writer_lock_path is None:
            raise SnapshotError("verified Diaries integration requires writer_lock_path")
        if config.writer_lock_path.parent != marker_parent:
            raise SnapshotError(
                "writer_lock_path must share the verified marker parent so receiver and snapshot manager "
                "coordinate the same whole-backup tree"
            )


def now_timestamp() -> str:
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def parse_timestamp(name: str) -> datetime:
    if not TIMESTAMP_RE.match(name):
        raise ValueError(name)
    return datetime.strptime(name, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


def create_all(config: Config, timestamp: str | None = None) -> str:
    if config.mode != "source":
        raise SnapshotError("receiver mode forbids snapshot creation")
    preflight(config)
    verification = read_verified_diaries(config, strict=True)
    if verification is not None:
        print(
            "VERIFIED-DIARIES "
            f"{verification['logicalDataset']} {verification['backupId']} "
            f"manifest={verification['manifestSha256']}"
        )
    stamp = timestamp or now_timestamp()
    try:
        parse_timestamp(stamp)
    except ValueError as exc:
        raise SnapshotError(f"invalid UTC snapshot timestamp: {stamp}") from exc

    create_sources = [source for source in config.sources if not config.creation_source_names or source.name in config.creation_source_names]
    destinations = [snapshot_path(config, source, stamp) for source in create_sources]
    existing = [path for path in destinations if path.exists()]
    if existing:
        raise SnapshotError(f"snapshot timestamp already exists: {stamp}: {existing}")

    created: list[Path] = []
    try:
        for source, destination in zip(create_sources, destinations):
            print(f"CREATE {source.name}: {source.source} -> {destination}")
            run(["btrfs", "subvolume", "snapshot", "-r", str(source.source), str(destination)])
            created.append(destination)
    except Exception:
        for destination in reversed(created):
            print(f"ROLLBACK {destination}", file=sys.stderr)
            run(["btrfs", "subvolume", "delete", str(destination)], check=False)
        raise

    print(f"Created timestamp set {stamp} ({len(created)} snapshots)")
    return stamp


def list_managed(config: Config, source: SnapshotSource) -> list[tuple[str, datetime, Path]]:
    directory = source_directory(config, source)
    snapshots: list[tuple[str, datetime, Path]] = []
    if not directory.exists():
        return snapshots
    for item in directory.iterdir():
        if not item.is_dir() or not TIMESTAMP_RE.match(item.name):
            continue
        try:
            dt = parse_timestamp(item.name)
        except ValueError:
            continue
        snapshots.append((item.name, dt, item))
    snapshots.sort(key=lambda entry: entry[1], reverse=True)
    return snapshots


def managed_snapshot_sets(config: Config) -> tuple[list[tuple[str, datetime]], dict[str, set[str]]]:
    by_timestamp: dict[str, set[str]] = {}
    dates: dict[str, datetime] = {}
    for source in config.sources:
        for name, dt, _ in list_managed(config, source):
            by_timestamp.setdefault(name, set()).add(source.name)
            dates[name] = dt
    complete_names = set(config.required_snapshot_sources or (source.name for source in config.sources))
    complete: list[tuple[str, datetime]] = []
    incomplete: dict[str, set[str]] = {}
    for name, present in by_timestamp.items():
        if complete_names.issubset(present):
            complete.append((name, dates[name]))
        else:
            incomplete[name] = present
    complete.sort(key=lambda row: row[1], reverse=True)
    return complete, incomplete


def bucket_hour(dt: datetime) -> tuple[int, int, int, int]:
    return dt.year, dt.month, dt.day, dt.hour


def bucket_day(dt: datetime) -> tuple[int, int, int]:
    return dt.year, dt.month, dt.day


def bucket_week(dt: datetime) -> tuple[int, int]:
    iso = dt.isocalendar()
    return iso.year, iso.week


def bucket_month(dt: datetime) -> tuple[int, int]:
    return dt.year, dt.month


def bucket_year(dt: datetime) -> tuple[int]:
    return (dt.year,)


def add_bucket_keeps(
    snapshots: Iterable[tuple[str, datetime, Path]],
    keep: set[str],
    limit: int,
    bucket: Callable[[datetime], tuple],
) -> None:
    if limit <= 0:
        return
    buckets: set[tuple] = set()
    for name, dt, _ in snapshots:
        key = bucket(dt)
        if key in buckets:
            continue
        buckets.add(key)
        keep.add(name)
        if len(buckets) >= limit:
            return


def retention_keep_set(
    snapshots: list[tuple[str, datetime, Path]], policy: RetentionPolicy, now: datetime
) -> set[str]:
    if not snapshots:
        return set()

    keep: set[str] = {snapshots[0][0]}
    minimum_age_seconds = policy.minimum_age_minutes * 60
    for name, dt, _ in snapshots:
        if (now - dt).total_seconds() < minimum_age_seconds:
            keep.add(name)

    add_bucket_keeps(snapshots, keep, policy.hourly, bucket_hour)
    add_bucket_keeps(snapshots, keep, policy.daily, bucket_day)
    add_bucket_keeps(snapshots, keep, policy.weekly, bucket_week)
    add_bucket_keeps(snapshots, keep, policy.monthly, bucket_month)
    add_bucket_keeps(snapshots, keep, policy.yearly, bucket_year)
    return keep




def agreed_parent_pins(config: Config) -> set[str]:
    """Optional 0040 state; if present protect all parent generations on either host.

    Absence preserves legacy behaviour while migration is incomplete. Existing
    malformed state is a hard stop, including for dry-run and receiver planning.
    The caller holds the manager lock for destructive source pruning.
    """
    directory = (config.snapshot_root if config.mode == "source" else config.receiver_state_dir)
    if directory is None:
        raise SnapshotError("receiver agreed-parent state directory missing")
    path = directory / ".agreed-parent.json"
    if not path.exists() and not path.is_symlink():
        return set()
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        raise SnapshotError("unsafe agreed-parent state path")
    metadata = path.stat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
            metadata.st_uid != 0 or metadata.st_mode & 0o077 or
            metadata.st_size > 65536):
        raise SnapshotError("unsafe agreed-parent ownership, mode or size")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if (type(state) is not dict or set(state) !=
                {"schema", "established", "pending", "previous"} or
                type(state["schema"]) is not int or state["schema"] != 1):
            raise ValueError("invalid agreed-parent schema")
        pins = {}
        for field in ("established", "pending", "previous"):
            record = state[field]
            if record is None:
                continue
            if (type(record) is not dict or set(record) != {"timestamp", "uuid"} or
                    type(record["timestamp"]) is not str or
                    not TIMESTAMP_RE.fullmatch(record["timestamp"]) or
                    type(record["uuid"]) is not str or
                    not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", record["uuid"])):
                raise ValueError("invalid agreed-parent snapshot")
            if record["timestamp"] in pins:
                raise ValueError("duplicate agreed-parent snapshot")
            pins[record["timestamp"]] = record["uuid"]
        if state["established"] is None or (state["pending"] is not None and state["previous"] is not None):
            raise ValueError("invalid agreed-parent transition")
        return set(pins)
    except (ValueError, OSError, TypeError, UnicodeError) as exc:
        raise SnapshotError(f"invalid agreed-parent state: {exc}") from exc

def simplified_agreed_parent_pins(config: Config) -> set[str]:
    """Protect the current and immediately prior parent during simple replication.

    This deliberately complements, rather than replaces, legacy holds and receipts.
    Missing file is allowed before the opt-in cutover. Invalid existing state stops
    pruning. The caller owns the normal snapshot-manager lock.
    """
    directory = (config.snapshot_root if config.mode == "source" else config.receiver_state_dir)
    if directory is None:
        raise SnapshotError("missing receiver agreed-parent directory")
    path = directory / ".simple-agreed-parent.json"
    if not path.exists() and not path.is_symlink():
        return set()
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        raise SnapshotError("unsafe simplified agreed-parent state")
    metadata = path.stat()
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or
            metadata.st_uid != 0 or metadata.st_mode & 0o077 or metadata.st_size > 4096):
        raise SnapshotError("unsafe simplified state ownership or size")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if (type(obj) is not dict or set(obj) != {"schema", "parent", "prior"} or
                type(obj["schema"]) is not int or obj["schema"] != 1):
            raise ValueError("invalid simplified state schema")
        def parse(item):
            if (type(item) is not dict or set(item) != {"timestamp", "uuid"} or
                    type(item["timestamp"]) is not str or
                    not TIMESTAMP_RE.fullmatch(item["timestamp"]) or
                    type(item["uuid"]) is not str or
                    not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", item["uuid"])):
                raise ValueError("invalid simplified parent record")
            return item["timestamp"]
        current = parse(obj["parent"])
        prior = parse(obj["prior"]) if obj["prior"] is not None else None
        if prior is not None and prior >= current:
            raise ValueError("invalid prior snapshot order")
        return {current} | ({prior} if prior else set())
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        raise SnapshotError(f"invalid simplified agreed-parent state: {exc}") from exc


def replication_pins(config: Config) -> set[str]:
    """Fail closed when replication protection is enabled; never prune unvalidated state."""
    if not config.replication_protection_required:
        return set()
    path = config.replication_protection_file
    if path is None or not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise SnapshotError("Replication protection state absent or unsafe; pruning prohibited")
    import stat
    metadata = path.stat()
    if metadata.st_uid != 0 or metadata.st_mode & 0o022:
        raise SnapshotError("Replication protection file must be root-owned and non-writable by others")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("schema") != 1 or not isinstance(state.get("protected"), dict):
            raise ValueError("Invalid protection schema")
        pins = state["protected"]
        if any(not re.fullmatch(r"[0-9]{8}-[0-9]{6}Z", stamp) or
               not isinstance(uuid, str) or not re.fullmatch(r"[0-9a-f-]{36}", uuid)
               for stamp, uuid in pins.items()):
            raise ValueError("Invalid pinned snapshot")
        return set(pins)
    except (ValueError, OSError, TypeError) as exc:
        raise SnapshotError(f"Unsafe replication protection: {exc}") from exc



def read_checkpoint_holds(config: Config) -> dict[str, dict[str, str]]:
    """Independently held recovery checkpoints. Invalid/missing enabled state blocks pruning."""
    if not config.checkpoint_holds_required:
        return {}
    path = config.checkpoint_holds_file
    if path is None or not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise SnapshotError("Checkpoint hold state absent or unsafe; pruning prohibited")
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_uid != 0 or metadata.st_mode & 0o077:
        raise SnapshotError("Checkpoint hold file must be regular, root-owned and mode 0600")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or set(raw) != {"schema", "holds"} or raw["schema"] != 1 or not isinstance(raw["holds"], dict):
            raise ValueError("invalid checkpoint hold schema")
        for stamp, record in raw["holds"].items():
            if not TIMESTAMP_RE.fullmatch(stamp) or not isinstance(record, dict) or set(record) != {"reason", "source_uuids"}:
                raise ValueError("invalid hold entry")
            if not isinstance(record["reason"], str) or not record["reason"].strip() or len(record["reason"]) > 256:
                raise ValueError("invalid hold reason")
            if not isinstance(record["source_uuids"], dict) or set(record["source_uuids"]) != {s.name for s in config.sources}:
                raise ValueError("invalid hold source list")
            if any(not isinstance(u, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", u)
                   for u in record["source_uuids"].values()):
                raise ValueError("invalid hold UUID")
        return raw["holds"]
    except (ValueError, OSError, TypeError) as exc:
        raise SnapshotError(f"Unsafe checkpoint hold state: {exc}") from exc


def write_checkpoint_holds(config: Config, holds: dict[str, dict[str, str]]) -> None:
    path = config.checkpoint_holds_file
    if path is None:
        raise SnapshotError("checkpoint hold file not configured")
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix=".checkpoint-holds-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({"schema": 1, "holds": holds}, out, indent=2, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def checkpoint_command(config: Config, command: str, timestamp: str | None, reason: str | None) -> None:
    if not config.checkpoint_holds_required:
        raise SnapshotError("checkpoint holds not enabled for this host")
    holds = read_checkpoint_holds(config)
    if command == "hold-list":
        for stamp, record in sorted(holds.items()):
            print(f"HELD {stamp} reason={record['reason']}")
        return
    assert timestamp is not None
    parse_timestamp(timestamp)
    if command == "hold-add":
        if timestamp in holds:
            raise SnapshotError("checkpoint already held; release explicitly before changing reason")
        if not reason or not reason.strip() or len(reason) > 256:
            raise SnapshotError("hold-add requires a reason (1-256 characters)")
        source_uuids = {}
        for source in config.sources:
            target = snapshot_path(config, source, timestamp)
            require_subvolume(target)
            result = run(["btrfs", "subvolume", "show", str(target)]).stdout
            match = re.search(r"^\s*UUID:\s*([0-9a-f-]{36})\s*$", result, re.M)
            if not match or not re.search(r"^\s*Flags:\s*readonly\s*$", result, re.M):
                raise SnapshotError(f"held snapshot must exist and be read-only: {target}")
            source_uuids[source.name] = match.group(1)
        holds[timestamp] = {"reason": reason.strip(), "source_uuids": source_uuids}
        write_checkpoint_holds(config, holds)
        print(f"HELD: {timestamp}")
    elif command == "hold-release":
        if timestamp not in holds:
            raise SnapshotError("checkpoint has no hold")
        # Never permit release of the active replication parent via the hold CLI.
        if timestamp in replication_pins(config):
            raise SnapshotError("cannot release a checkpoint while it is the protected replication parent")
        del holds[timestamp]
        write_checkpoint_holds(config, holds)
        print(f"RELEASED: {timestamp}")

def validate_prune_candidate(config: Config, source: SnapshotSource, timestamp: str) -> None:
    """Refuse unmanaged paths, symlinks, writable snapshots and non-subvolumes."""
    if not TIMESTAMP_RE.fullmatch(timestamp):
        raise SnapshotError(f"invalid managed timestamp: {timestamp}")
    candidate = snapshot_path(config, source, timestamp)
    parent = source_directory(config, source)
    if parent.is_symlink() or candidate.is_symlink() or not candidate.is_dir():
        raise SnapshotError(f"unsafe prune candidate: {candidate}")
    if candidate.parent.resolve(strict=True) != parent.resolve(strict=True):
        raise SnapshotError(f"candidate outside managed source: {candidate}")
    require_subvolume(candidate)
    flags = run(["btrfs", "property", "get", "-ts", str(candidate), "ro"]).stdout.strip()
    if flags != "ro=true":
        raise SnapshotError(f"refusing writable snapshot deletion: {candidate}: {flags}")



def native_prune_subvolume_id(path: Path) -> int:
    """Read the exact subvolume ID before native deletion for qgroup correlation.

    An unreadable or ambiguous ID fails closed: it must not be replaced with a
    guessed ID or silently recorded as an authoritative deletion identity.
    """
    output = run(["btrfs", "subvolume", "show", str(path)]).stdout
    matches = re.findall(r"^\s*Subvolume ID:\s*(\d+)\s*$", output, re.M)
    if len(matches) != 1 or int(matches[0]) <= 0:
        raise SnapshotError(f"cannot establish subvolume ID before native prune: {path}")
    return int(matches[0])


SOURCE_PRUNE_MAX_SETS_PER_RUN = 32


def prune(config: Config, dry_run: bool = False, max_delete: int | None = None) -> int:
    # A bounded scheduled prune prevents an accumulated backlog from being
    # deleted in one run. Keep direct legacy invocations backward-compatible.
    if max_delete is not None and (type(max_delete) is not int or not 1 <= max_delete <= SOURCE_PRUNE_MAX_SETS_PER_RUN):
        raise SnapshotError("source prune max_delete must be between 1 and 32")
    if config.mode != "source":
        raise SnapshotError("receiver pruning is not implemented; fail closed")
    preflight(config)
    complete, incomplete = managed_snapshot_sets(config)
    if incomplete:
        detail = ", ".join(f"{stamp}:{sorted(names)}" for stamp, names in sorted(incomplete.items()))
        raise SnapshotError(f"refusing retention with incomplete timestamp sets: {detail}")
    now = datetime.now(timezone.utc)
    synthetic = [(name, dt, config.snapshot_root / name) for name, dt in complete]
    keep = retention_keep_set(synthetic, config.retention, now)
    pins = replication_pins(config)
    keep.update(pins)
    keep.update(agreed_parent_pins(config))
    keep.update(simplified_agreed_parent_pins(config))
    holds = read_checkpoint_holds(config)
    keep.update(holds)
    if holds:
        print(f"CHECKPOINT-HELD: {sorted(holds)}")
    if pins:
        print(f"REPLICATION-PROTECTED: {sorted(pins)}")
    # Historical sources remain inventoried but need not be eligible for routine pruning.
    # The default (no explicit selection) retains legacy all-sources behaviour.
    prune_sources = [source for source in config.sources
                     if not config.prune_source_names or source.name in config.prune_source_names]
    # Validate the *entire* deletion plan before touching any selected snapshot.
    # In particular, do not delete one half of a root/@data pair if its peer is unsafe.
    candidates = [(name, source) for name, _ in complete if name not in keep
                  for source in prune_sources if snapshot_path(config, source, name).exists()]
    for name, source in candidates:
        validate_prune_candidate(config, source, name)
    # Evaluate and validate every eligible snapshot, even when the run is
    # capped. Selection follows the existing newest-first iteration order.
    eligible = [name for name, _ in complete if name not in keep]
    selected = set(eligible[:max_delete]) if max_delete is not None else set(eligible)
    deleted_sets = 0
    print(f"RETENTION sets: total={len(complete)} keep={len(keep)} sources={len(config.sources)}")
    if max_delete is not None:
        print(f"PRUNE-CAP: eligible={len(eligible)} selected={len(selected)} max_delete={max_delete}")
    for name, _ in complete:
        if name not in selected:
            continue
        deleted_sets += 1
        if dry_run:
            for source in prune_sources:
                if snapshot_path(config, source, name).exists():
                    print(f"WOULD-DELETE {source.name} {name} {snapshot_path(config, source, name)}")
            continue
        for source in reversed(prune_sources):
            path = snapshot_path(config, source, name)
            if not path.exists():
                continue
            subvolume_id = native_prune_subvolume_id(path)
            print(f"DELETE {source.name} {name} subvol_id={subvolume_id} {path}", flush=True)
            run(["btrfs", "subvolume", "delete", str(path)])
    print(("Would delete" if dry_run else "Deleted") + f" {deleted_sets} complete timestamp sets")
    return deleted_sets


def receiver_inventory(config: Config) -> None:
    """Read-only receipt/UUID inventory. Never accepts, prunes or repairs state."""
    if config.mode != "receiver" or config.receiver_state_dir is None:
        raise SnapshotError("receiver-inventory requires receiver mode")
    preflight(config)
    state = config.receiver_state_dir
    if not state.is_dir() or state.is_symlink():
        raise SnapshotError("unsafe receiver state directory")
    source = config.sources[0]
    entries = list_managed(config, source)
    print(f"RECEIVER-INVENTORY snapshots={len(entries)} directory={source_directory(config, source)}")
    problems = 0
    for stamp, _, path in entries:
        receipt_path = state / (stamp + ".json")
        try:
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise SnapshotError("missing/unsafe receipt")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (receipt.get("schema") != 1 or receipt.get("snapshot") != stamp or
                    receipt.get("destination") != str(path) or
                    receipt.get("read_only_verified") is not True or
                    receipt.get("source_uuid") != receipt.get("received_uuid")):
                raise SnapshotError("invalid receipt fields")
            output = run(["btrfs", "subvolume", "show", str(path)]).stdout
            matches = re.findall(r"^\s*Received UUID:\s*(\S+)\s*$", output, re.M)
            if len(matches) != 1 or matches[0] != receipt.get("source_uuid"):
                raise SnapshotError("received UUID mismatch")
            ro = run(["btrfs", "property", "get", "-ts", str(path), "ro"]).stdout.strip()
            if ro != "ro=true":
                raise SnapshotError("snapshot is not read-only")
            print(f"VERIFIED {stamp} source_uuid={matches[0]}")
        except (SnapshotError, OSError, ValueError, TypeError) as exc:
            problems += 1
            print(f"UNVERIFIED {stamp}: {exc}")
    # A receipt without its corresponding snapshot is also inconsistent state.
    known = {stamp for stamp, _, _ in entries}
    for receipt_path in sorted(state.glob("*.json")):
        # 0040: agreed-parent state is metadata, not a replication receipt.
        # Only this exact reserved name is exempt; unexpected JSON remains fail-closed.
        if receipt_path.name == ".agreed-parent.json":
            continue
        if receipt_path.is_symlink() or receipt_path.stem not in known:
            problems += 1
            print(f"UNVERIFIED receipt={receipt_path.name}: missing or unsafe snapshot")
    print(f"RECEIVER-INVENTORY problems={problems}")
    if problems:
        raise SnapshotError("receiver inventory contains unverified snapshots")
    return entries


def receiver_verified_checkpoint_holds(config: Config, entries: list[tuple[str, datetime, Path]]) -> set[str]:
    """Root-authorised receiver holds; block destructive use until configured.

    The hold file's source UUID is bound to the matching verified receiver
    receipt. Merely listing a timestamp is not sufficient for deletion safety.
    """
    if config.mode != "receiver" or config.receiver_state_dir is None:
        raise SnapshotError("receiver checkpoint holds require receiver mode")
    if not config.checkpoint_holds_required:
        raise SnapshotError("receiver checkpoint holds not configured; deletion prohibited")
    holds = read_checkpoint_holds(config)  # root-owned, 0600, validated schema
    paths = {stamp: path for stamp, _, path in entries}
    for stamp, record in holds.items():
        if stamp not in paths:
            raise SnapshotError(f"held receiver checkpoint absent: {stamp}")
        receipt_path = config.receiver_state_dir / (stamp + ".json")
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise SnapshotError(f"held receiver checkpoint receipt unsafe: {stamp}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        expected = record["source_uuids"][config.sources[0].name]
        if (receipt.get("schema") != 1 or receipt.get("snapshot") != stamp or
                receipt.get("destination") != str(paths[stamp]) or
                receipt.get("source_uuid") != expected or
                receipt.get("received_uuid") != expected or
                receipt.get("read_only_verified") is not True):
            raise SnapshotError(f"held receiver checkpoint UUID mismatch: {stamp}")
    return set(holds)


def receiver_plan(config: Config, *, now: datetime | None = None) -> dict[str, object]:
    """Read-only bucket retention selection over verified received snapshots.

    No deletion, receipt mutation, or independently assumed common-parent selection.
    Candidate status is advisory; guarded execution belongs to a later gate.
    """
    if config.mode != "receiver":
        raise SnapshotError("receiver-plan requires receiver mode")
    if config.receiver_state_dir is None:
        raise SnapshotError("receiver retention planning requires receiver state directory")
    transfer_pending = config.receiver_state_dir / ".agreed-parent-transfer-pending.json"
    if transfer_pending.exists() or transfer_pending.is_symlink():
        raise SnapshotError("unfinished agreed-parent transfer blocks receiver pruning")
    pending = config.receiver_state_dir / ".receiver-prune-pending.json"
    if pending.exists() or pending.is_symlink():
        raise SnapshotError("pending receiver prune transaction blocks retention planning")
    entries = receiver_inventory(config)  # Fail closed on every invalid receipt or snapshot.
    clock = now if now is not None else datetime.now(timezone.utc)
    keep = retention_keep_set(entries, config.retention, clock)
    keep.update(agreed_parent_pins(config))
    keep.update(simplified_agreed_parent_pins(config))
    if entries:
        keep.add(entries[0][0])  # Explicit most recent common-parent candidate.
    if config.checkpoint_holds_required:
        keep.update(receiver_verified_checkpoint_holds(config, entries))
    candidate_names = [stamp for stamp, _, _ in entries if stamp not in keep]
    print(f"RECEIVER-PLAN total={len(entries)} retention_keep={len(keep)} "
          f"candidate_count={len(candidate_names)} executable=false")
    for stamp, _, _ in entries:
        print(f"{'RETAIN' if stamp in keep else 'CANDIDATE-NOT-AUTHORIZED'} {stamp}")
    return {"keep": sorted(keep), "candidates": candidate_names, "executable": False}




def receiver_coordination_check(config: Config, parent_stamp: str, source_uuid: str) -> dict[str, object]:
    """Read-only receiver-side parent validation under writer.lock.

    The CLI acquires manager lock then the *same* exclusive writer.lock used by
    native receive. This observation is NOT a cross-host deletion authority:
    it cannot guarantee mars still holds the source pin, so authorizes_prune
    always remains false. A later stage must establish a lock-held protocol
    across both hosts before allowing a destructive receiver transaction.
    """
    if config.mode != "receiver" or config.receiver_state_dir is None:
        raise SnapshotError("receiver coordination requires receiver mode")
    if (config.writer_lock_path is None or
            config.writer_lock_path != config.receiver_state_dir / "writer.lock"):
        raise SnapshotError("receiver coordination requires receiver writer.lock")
    if not TIMESTAMP_RE.fullmatch(parent_stamp):
        raise SnapshotError("invalid common-parent snapshot name")
    if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", source_uuid):
        raise SnapshotError("invalid common-parent source UUID")
    entries = receiver_inventory(config)  # All receipts and snapshots must verify.
    matches = [path for stamp, _, path in entries if stamp == parent_stamp]
    if len(matches) != 1:
        raise SnapshotError("common parent is absent from verified receiver inventory")
    receipt_path = config.receiver_state_dir / (parent_stamp + ".json")
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise SnapshotError("common-parent receipt absent or unsafe")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("source_uuid") != source_uuid:
        raise SnapshotError("common-parent source UUID mismatch")
    transfer_pending = config.receiver_state_dir / ".agreed-parent-transfer-pending.json"
    if transfer_pending.exists() or transfer_pending.is_symlink():
        raise SnapshotError("unfinished agreed-parent transfer blocks receiver pruning")
    pending = config.receiver_state_dir / ".receiver-prune-pending.json"
    if pending.exists() or pending.is_symlink():
        raise SnapshotError("pending receiver prune transaction needs operator reconciliation")
    result = {"snapshot": parent_stamp, "source_uuid": source_uuid,
              "receiver_verified_under_lock": True, "source_pin_verified": False,
              "authorizes_prune": False}
    print("RECEIVER-COORDINATION " + json.dumps(result, sort_keys=True))
    return result


def receiver_recovery_plan(config: Config) -> dict[str, object]:
    """Classify an interrupted receiver prune; no repairs or deletion.

    Caller must hold manager lock, then the exact receiver writer.lock.
    Only the receipt and snapshot identified by the pending journal are
    inspected. The journal is NEVER treated as permission to modify either.
    """
    if config.mode != "receiver" or config.receiver_state_dir is None:
        raise SnapshotError("receiver recovery requires receiver mode")
    if config.writer_lock_path != config.receiver_state_dir / "writer.lock":
        raise SnapshotError("receiver recovery requires the exact receiver writer.lock")
    state = config.receiver_state_dir
    journal = state / ".receiver-prune-pending.json"
    if journal.is_symlink():
        raise SnapshotError("unsafe receiver prune journal symlink")
    if not journal.exists():
        result = {"state": "CLEAN", "authorizes_repair": False}
        print("RECEIVER-RECOVERY " + json.dumps(result, sort_keys=True))
        return result
    if not journal.is_file():
        raise SnapshotError("unsafe receiver prune journal")
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SnapshotError("unreadable receiver prune journal") from exc
    if not isinstance(record, dict) or record.get("schema") != 1:
        raise SnapshotError("unexpected receiver prune journal schema")
    stamp = record.get("snapshot")
    if not isinstance(stamp, str) or not TIMESTAMP_RE.fullmatch(stamp):
        raise SnapshotError("invalid receiver prune journal snapshot")
    snapshot = source_directory(config, config.sources[0]) / stamp
    receipt = state / (stamp + ".json")
    if record.get("destination") != str(snapshot) or record.get("receipt") != str(receipt):
        raise SnapshotError("receiver prune journal path mismatch")
    uid = record.get("source_uuid")
    if not isinstance(uid, str) or not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", uid):
        raise SnapshotError("invalid receiver prune journal UUID")
    if snapshot.is_symlink() or receipt.is_symlink():
        raise SnapshotError("unsafe receiver prune target symlink")
    has_snapshot, has_receipt = snapshot.exists(), receipt.exists()
    if has_snapshot and not snapshot.is_dir():
        raise SnapshotError("receiver prune target is not a directory")
    if has_receipt:
        if not receipt.is_file():
            raise SnapshotError("unsafe receiver prune receipt")
        try:
            saved = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SnapshotError("unreadable receiver prune receipt") from exc
        if (not isinstance(saved, dict) or saved.get("schema") != 1 or
                saved.get("snapshot") != stamp or saved.get("destination") != str(snapshot) or
                saved.get("source_uuid") != uid or saved.get("received_uuid") != uid or
                saved.get("read_only_verified") is not True):
            raise SnapshotError("receiver prune receipt disagrees with pending journal")
    if has_snapshot:
        # A path alone is insufficient: confirm the identity before classifying.
        info = run(["btrfs", "subvolume", "show", str(snapshot)]).stdout
        received = re.findall(r"^\s*Received UUID:\s*(\S+)\s*$", info, re.M)
        if received != [uid]:
            raise SnapshotError("receiver prune snapshot UUID differs from journal")
        ro = run(["btrfs", "property", "get", "-ts", str(snapshot), "ro"]).stdout.strip()
        if ro != "ro=true":
            raise SnapshotError("receiver prune snapshot is not read-only")
    phase = ("BEFORE_DELETE" if has_snapshot and has_receipt else
             "AFTER_DELETE_RECEIPT_PRESENT" if not has_snapshot and has_receipt else
             "AFTER_RECEIPT_REMOVAL" if not has_snapshot else "INCONSISTENT")
    result = {"state": phase, "snapshot": stamp, "authorizes_repair": False}
    print("RECEIVER-RECOVERY " + json.dumps(result, sort_keys=True))
    return result


def receiver_journal_write(directory: Path, record: dict[str, object]) -> Path:
    """Durably create one pending transaction, refusing overwrite or symlinks.

    Caller must already hold the manager lock and receiver writer.lock. This
    internal primitive does not grant prune authority and is not exposed in CLI.
    The directory sync makes the new journal name durable before a destructive
    operation can be attempted by a future approved executor.
    """
    if directory.is_symlink() or not directory.is_dir():
        raise SnapshotError("unsafe receiver journal directory")
    if (not isinstance(record, dict) or record.get("schema") != 1 or
            not isinstance(record.get("snapshot"), str) or
            not TIMESTAMP_RE.fullmatch(record["snapshot"]) or
            not isinstance(record.get("source_uuid"), str) or
            not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", record["source_uuid"])):
        raise SnapshotError("invalid pending receiver transaction")
    pending = directory / ".receiver-prune-pending.json"
    # Opening the containing directory guards against a renamed or substituted
    # path during name creation; O_EXCL refuses an existing pending transaction.
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(pending.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory_fd)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(record, output, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return pending


def receiver_journal_finish(directory: Path, *, snapshot: str) -> None:
    """Durably clear a finished journal; caller holds both receiver locks.

    Journal removal is only allowed when the corresponding snapshot and receipt
    have already been removed. This does not perform either deletion.
    """
    if not TIMESTAMP_RE.fullmatch(snapshot):
        raise SnapshotError("invalid receiver transaction timestamp")
    if directory.is_symlink() or not directory.is_dir():
        raise SnapshotError("unsafe receiver journal directory")
    pending = directory / ".receiver-prune-pending.json"
    if pending.is_symlink() or not pending.is_file():
        raise SnapshotError("missing or unsafe pending transaction")
    record = json.loads(pending.read_text(encoding="utf-8"))
    if record.get("schema") != 1 or record.get("snapshot") != snapshot:
        raise SnapshotError("receiver transaction identity mismatch")
    if (directory / (snapshot + ".json")).exists():
        raise SnapshotError("receiver receipt still exists")
    if Path(record.get("destination", "")).exists():
        raise SnapshotError("receiver snapshot still exists")
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.unlink(pending.name, dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)




def receiver_transaction_test_sequence(
    directory: Path,
    record: dict[str, object],
    *,
    verify_protection: Callable[[], None],
    delete_disposable_snapshot: Callable[[], None],
    remove_disposable_receipt: Callable[[], None],
) -> None:
    """Exercise journal ordering with injected disposable-only operations.

    This is deliberately NOT a production deletion executor. It does not call
    btrfs, has no command-line entry point, and does not confer authorisation.
    The caller provides test-only callbacks, runs under exclusive disposable
    locks and is responsible for staging an isolated fixture. Future production
    execution must implement cross-host lease validation *under* receiver lock
    and separate explicit approval before reusing these journal primitives.
    Any exception leaves the pending journal in place for recovery inspection.
    """
    if directory.is_symlink() or not directory.is_dir():
        raise SnapshotError("unsafe test transaction directory")
    stamp = record.get("snapshot")
    if not isinstance(stamp, str) or not TIMESTAMP_RE.fullmatch(stamp):
        raise SnapshotError("invalid test transaction snapshot")
    receipt = directory / (stamp + ".json")
    destination = record.get("destination")
    if record.get("receipt") != str(receipt) or not isinstance(destination, str):
        raise SnapshotError("test transaction record path mismatch")
    path = Path(destination)
    if (path.is_symlink() or receipt.is_symlink() or
            not path.is_dir() or not receipt.is_file()):
        raise SnapshotError("test transaction inputs missing or unsafe")
    saved = json.loads(receipt.read_text(encoding="utf-8"))
    if (saved.get("schema") != 1 or saved.get("snapshot") != stamp or
            saved.get("destination") != destination or
            saved.get("source_uuid") != record.get("source_uuid") or
            saved.get("received_uuid") != record.get("source_uuid")):
        raise SnapshotError("test receipt identity mismatch")
    # The callback must fail closed on any missing source protection. A real
    # production implementation cannot trust an externally supplied callback.
    verify_protection()
    receiver_journal_write(directory, record)
    delete_disposable_snapshot()
    if path.exists() or path.is_symlink():
        raise SnapshotError("test snapshot deletion not complete")
    remove_disposable_receipt()
    if receipt.exists() or receipt.is_symlink():
        raise SnapshotError("test receipt deletion not complete")
    receiver_journal_finish(directory, snapshot=stamp)


def receiver_refuse_unfinished_transfer(state: Path) -> None:
    """Fail closed at the receiver deletion boundary, not just in planning.

    Caller must hold manager and writer locks. An unresolved transfer marker
    (including a symlink or dangling symlink) blocks destructive operations.
    """
    marker = state / ".agreed-parent-transfer-pending.json"
    if marker.exists() or marker.is_symlink():
        raise SnapshotError("unfinished agreed-parent transfer blocks receiver deletion")


def receiver_delete_one_locked(
    config: Config,
    stamp: str,
    *,
    protected_stamp: str,
    expected_parent_uuid: str,
    verify_source_pin: Callable[[], None],
    delete_subvolume: Callable[[Path], None],
) -> None:
    """Single receiver deletion transaction; INTERNAL, never exposed as CLI.

    Caller MUST hold manager + receiver writer locks for the entire call, and
    hold a source-coordination context that prevents releasing the source pin.
    The callback is deliberately injected for disposable regression tests.
    Neither the public receiver CLI nor the sender currently grants this
    capability. Recovery is operator-gated after any partial failure.
    """
    if config.mode != "receiver" or config.receiver_state_dir is None:
        raise SnapshotError("receiver-only transaction")
    if config.writer_lock_path != config.receiver_state_dir / "writer.lock":
        raise SnapshotError("receiver writer lock mismatch")
    if not TIMESTAMP_RE.fullmatch(stamp) or not TIMESTAMP_RE.fullmatch(protected_stamp):
        raise SnapshotError("invalid transaction snapshot name")
    # Defence in depth: the transaction must enforce the incremental-parent
    # boundary independently of the sender and advisory retention planner.
    if stamp >= protected_stamp:
        raise SnapshotError("cannot delete protected parent or newer snapshot")
    if not isinstance(expected_parent_uuid, str) or not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", expected_parent_uuid):
        raise SnapshotError("invalid expected protected parent UUID")
    state = config.receiver_state_dir
    receiver_refuse_unfinished_transfer(state)
    pending = state / ".receiver-prune-pending.json"
    if pending.exists() or pending.is_symlink():
        raise SnapshotError("pending transaction requires manual recovery")
    entries = receiver_inventory(config)
    available = {name: path for name, _, path in entries}
    if stamp not in available or protected_stamp not in available:
        raise SnapshotError("snapshot or protected parent not verified")
    keep = retention_keep_set(entries, config.retention, datetime.now(timezone.utc))
    if entries:
        keep.add(entries[0][0])
    # Mandatory, independent recovery hold gate for future receiver deletion.
    # An unset or invalid hold file blocks all receiver deletion transactions.
    keep.update(receiver_verified_checkpoint_holds(config, entries))
    if stamp in keep:
        raise SnapshotError("snapshot is retained by policy or recovery checkpoint hold")
    source = config.sources[0]
    path = available[stamp]
    receipt = state / (stamp + ".json")
    validate_prune_candidate(config, source, stamp)
    native_prune_subvolume_id(path)
    data = json.loads(receipt.read_text(encoding="utf-8"))
    parent_receipt_path = state / (protected_stamp + ".json")
    if parent_receipt_path.is_symlink() or not parent_receipt_path.is_file():
        raise SnapshotError("protected parent receipt missing or unsafe")
    parent_data = json.loads(parent_receipt_path.read_text(encoding="utf-8"))
    parent_uuid = parent_data.get("source_uuid")
    if (parent_data.get("schema") != 1 or parent_data.get("snapshot") != protected_stamp or
            parent_data.get("destination") != str(available[protected_stamp]) or
            parent_data.get("received_uuid") != parent_uuid or
            parent_uuid != expected_parent_uuid or
            parent_data.get("read_only_verified") is not True or
            not isinstance(parent_uuid, str) or
            not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", parent_uuid)):
        raise SnapshotError("protected parent receipt identity mismatch")
    record = {"schema": 1, "snapshot": stamp, "destination": str(path),
              "receipt": str(receipt), "source_uuid": data["source_uuid"],
              "protected_parent": protected_stamp, "protected_parent_uuid": parent_uuid}
    # Recheck while the caller's source-protection context is still held.
    verify_source_pin()
    receiver_refuse_unfinished_transfer(state)
    receiver_journal_write(state, record)
    try:
        delete_subvolume(path)
        if path.exists() or path.is_symlink():
            raise SnapshotError("deleted snapshot still exists")
        # A receipt is removed only after Btrfs confirms the path is absent.
        if receipt.is_symlink() or not receipt.is_file():
            raise SnapshotError("receipt missing or unsafe after delete")
        current = json.loads(receipt.read_text(encoding="utf-8"))
        if (current.get("schema") != 1 or current.get("snapshot") != stamp or
                current.get("source_uuid") != record["source_uuid"] or
                current.get("destination") != str(path)):
            raise SnapshotError("receipt changed during transaction")
        receipt.unlink()
        directory_fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        receiver_journal_finish(state, snapshot=stamp)
    except Exception:
        # Preserve the journal and source pin for operator reconciliation.
        raise


def receiver_guarded_prune(config: Config, approval_file: Path | None = None) -> int:
    """Production deletion remains disabled pending a trusted source-held lease.

    The internal transaction above is intentionally not connected to this CLI.
    A root-owned approval file is not proof that a source pin remains held.
    """
    raise SnapshotError("receiver pruning blocked: live common-parent coordination not implemented")



# 0040 Step 12 — the same snapshot manager/retention algorithm is used at both
# endpoints.  The simplified receiver creates no legacy receipt, so receiver
# inventory is established from Btrfs itself, not from legacy receipt claims.
_SIMPLE_RECEIVER_ROOT = Path("/@data/mars-received")
_SIMPLE_RECEIVED = _SIMPLE_RECEIVER_ROOT / "@data"
_SIMPLE_STATE = _SIMPLE_RECEIVER_ROOT / ".replication-state"
_SIMPLE_RECEIVER_FS = "b915f967-7cb4-4c14-b11b-f52209637a22"
_SIMPLE_RECEIVER_MOUNT = Path("/")
_SIMPLE_MANAGER_LOCK = Path("/run/lock/btrfs-snapshot-manager.lock")
_SIMPLE_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_SIMPLE_BLOCKERS = (
    ".agreed-parent-transfer-pending.json",
    ".agreed-parent-provisional.json",
    ".receiver-prune-pending.json",
    ".simple-prune-pending.json",
)


def receiver_simple_identity(path: Path) -> dict[str, str]:
    """The authoritative identity of a single, read-only Btrfs receive."""
    if path.is_symlink() or not path.is_dir():
        raise SnapshotError(f"unsafe received snapshot: {path}")
    output = run(["btrfs", "subvolume", "show", str(path)]).stdout
    fields = {}
    for field in ("UUID", "Received UUID"):
        matches = re.findall(r"^\s*" + field + r":\s*(\S+)\s*$", output, re.M)
        if len(matches) != 1 or not _SIMPLE_UUID.fullmatch(matches[0]):
            raise SnapshotError(f"invalid {field} for received snapshot: {path}")
        fields[field] = matches[0]
    ro = run(["btrfs", "property", "get", "-ts", str(path), "ro"]).stdout.strip()
    if ro != "ro=true":
        raise SnapshotError(f"writable received snapshot: {path}")
    fields["Subvolume ID"] = str(native_prune_subvolume_id(path))
    return fields


def receiver_simple_validate(config: Config) -> None:
    """Fail-closed fixed-root, lock and filesystem boundary."""
    if (config.mode != "receiver" or config.snapshot_root != _SIMPLE_RECEIVER_ROOT or
            config.receiver_state_dir != _SIMPLE_STATE or
            len(config.sources) != 1 or
            source_directory(config, config.sources[0]) != _SIMPLE_RECEIVED or
            config.lock_path != _SIMPLE_MANAGER_LOCK):
        raise SnapshotError("unexpected simplified receiver configuration")
    preflight(config)
    if not _SIMPLE_STATE.is_dir() or _SIMPLE_STATE.is_symlink():
        raise SnapshotError("unsafe receiver state directory")
    filesystem = run(["btrfs", "filesystem", "show", str(_SIMPLE_RECEIVER_MOUNT)]).stdout
    if not re.search(r"\buuid:\s*" + re.escape(_SIMPLE_RECEIVER_FS) + r"\b", filesystem, re.I):
        raise SnapshotError("unexpected receiver filesystem UUID")
    for filename in _SIMPLE_BLOCKERS:
        entry = _SIMPLE_STATE / filename
        if entry.exists() or entry.is_symlink():
            raise SnapshotError(f"unfinished transaction blocks receiver retention: {filename}")


def receiver_simple_plan(config: Config, *, now: datetime | None = None) -> dict[str, object]:
    """Non-mutating cross-generation retention using existing bucket policy.

    A legacy receipt remains immutable forensic evidence, not a permanent
    exemption from the configured retention buckets.  Receipt data is never
    accepted as Btrfs identity proof, and an orphan receipt after a normal
    prune is permitted. Current/prior parents are checked against actual
    received UUIDs, including after cutover.
    The caller must hold the same manager lock as simplified receive.
    """
    receiver_simple_validate(config)
    directory = _SIMPLE_RECEIVED
    # list_managed intentionally ignores symlinks; they must not hide inside
    # a retention plan which otherwise appears complete.
    for path in directory.iterdir():
        if TIMESTAMP_RE.fullmatch(path.name) and (path.is_symlink() or not path.is_dir()):
            raise SnapshotError(f"unexpected received snapshot entry: {path}")
    entries = list_managed(config, config.sources[0])
    identity = {stamp: receiver_simple_identity(path) for stamp, _, path in entries}
    if len({item["Received UUID"] for item in identity.values()}) != len(identity):
        raise SnapshotError("duplicate received UUID in receiver dataset")
    pins = simplified_agreed_parent_pins(config)
    if not pins:
        raise SnapshotError("simplified agreed parent missing")
    state = json.loads((_SIMPLE_STATE / ".simple-agreed-parent.json").read_text(encoding="utf-8"))
    for name in ("parent", "prior"):
        value = state[name]
        if value is not None:
            stamp = value["timestamp"]
            if stamp not in identity or identity[stamp]["Received UUID"] != value["uuid"]:
                raise SnapshotError(f"simplified {name} Btrfs identity mismatch: {stamp}")
    # Keep all newer-than-parent objects, even if a previous completed transfer
    # has not yet been acknowledged by the sender.
    current_stamp = state["parent"]["timestamp"]
    keep = retention_keep_set(entries, config.retention, now or datetime.now(timezone.utc))
    keep.update(pins)
    keep.update(stamp for stamp in identity if stamp >= current_stamp)
    keep.update(agreed_parent_pins(config))

    # Independently protected checkpoints: bind the hold UUID to the real
    # Btrfs Received UUID rather than an untrusted historical receipt.
    if not config.checkpoint_holds_required:
        raise SnapshotError("receiver checkpoint holds are mandatory")
    holds = read_checkpoint_holds(config)
    for stamp, value in holds.items():
        if (stamp not in identity or
                identity[stamp]["Received UUID"] != value["source_uuids"][config.sources[0].name]):
            raise SnapshotError(f"checkpoint hold identity mismatch: {stamp}")
    keep.update(holds)

    # The new sender produces no legacy receipts. Retain all historical
    # receipts as forensic evidence without using their contents as proof of
    # received identity or as an indefinite retention pin. After an approved
    # prune, a receipt for a deleted snapshot is *expected* to remain on disk.
    # Timestamp-named symlink/non-file entries are still rejected outright.
    historical_receipts = set()
    for path in _SIMPLE_STATE.iterdir():
        if not path.name.endswith(".json") or not TIMESTAMP_RE.fullmatch(path.stem):
            continue
        if path.is_symlink() or not path.is_file():
            raise SnapshotError(f"unsafe historical receipt: {path}")
        historical_receipts.add(path.stem)
    candidates = [stamp for stamp, _, _ in entries if stamp not in keep]
    receipt_candidates = sorted(set(candidates).intersection(historical_receipts))
    orphan_receipts = sorted(historical_receipts.difference(identity))
    return {
        "parent": state["parent"], "prior": state["prior"],
        "keep": sorted(keep), "candidates": candidates,
        "identity": identity, "historical_receipts": sorted(historical_receipts),
        "historical_receipts_on_candidates": receipt_candidates,
        "historical_receipts_orphaned": orphan_receipts,
        "holds": sorted(holds), "executable": config.receiver_prune_enabled,
    }


def receiver_simple_print_plan(plan: dict[str, object]) -> None:
    print("RECEIVER-SIMPLE-PLAN " + json.dumps({
        "parent": plan["parent"], "prior": plan["prior"],
        "keep": len(plan["keep"]), "candidates": len(plan["candidates"]),
        "historical_receipts_preserved": len(plan["historical_receipts"]),
        "historical_receipts_on_candidates": len(plan["historical_receipts_on_candidates"]),
        "historical_receipts_orphaned": len(plan["historical_receipts_orphaned"]),
        "holds": plan["holds"], "enabled": plan["executable"],
    }, sort_keys=True))
    keep = set(plan["keep"])
    for stamp in sorted(plan["identity"], reverse=True):
        label = ("RETAIN" if stamp in keep else
                 "ELIGIBLE-WHEN-APPROVED" if plan["executable"] else
                 "CANDIDATE-NOT-AUTHORIZED")
        receipt_note = " historical_receipt=preserved" if stamp in plan["historical_receipts"] else ""
        print(f"{label} {stamp} received_uuid={plan['identity'][stamp]['Received UUID']} "
              f"subvolume_id={plan['identity'][stamp]['Subvolume ID']}{receipt_note}")


def receiver_simple_prune(config: Config, *, max_delete: int) -> int:
    """Guarded receiver-only deletion.  Caller holds manager flock throughout.

    No legacy receipt is ever removed. A durable single-candidate journal
    blocks subsequent runs if deletion or verification is interrupted.
    """
    if config.receiver_prune_enabled is not True:
        raise SnapshotError("receiver pruning disabled by configuration")
    if not isinstance(max_delete, int) or not 1 <= max_delete <= 20:
        raise SnapshotError("max-delete must be within 1..20")
    plan = receiver_simple_plan(config)
    deleted = 0
    journal = _SIMPLE_STATE / ".simple-prune-pending.json"
    for stamp in plan["candidates"][:max_delete]:
        # Re-evaluate policy/state/holds for every candidate before mutation.
        latest = receiver_simple_plan(config)
        if stamp not in latest["candidates"]:
            raise SnapshotError(f"candidate no longer eligible: {stamp}")
        expected = plan["identity"][stamp]
        if latest["identity"][stamp] != expected:
            raise SnapshotError(f"candidate identity changed: {stamp}")
        path = _SIMPLE_RECEIVED / stamp
        validate_prune_candidate(config, config.sources[0], stamp)
        if str(native_prune_subvolume_id(path)) != expected["Subvolume ID"]:
            raise SnapshotError(f"candidate subvolume ID changed: {stamp}")
        if journal.exists() or journal.is_symlink():
            raise SnapshotError("unfinished receiver prune transaction")
        payload = {"schema": 1, "candidate": stamp,
                   "received_uuid": expected["Received UUID"],
                   "subvolume_id": expected["Subvolume ID"],
                   "parent": latest["parent"], "prior": latest["prior"]}
        fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        parent_fd = os.open(_SIMPLE_STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        # No catch-and-retry here: preserve the journal on any uncertainty.
        run(["btrfs", "subvolume", "delete", str(path)])
        if path.exists() or path.is_symlink():
            raise SnapshotError(f"receiver deletion not confirmed: {stamp}")
        journal.unlink()
        parent_fd = os.open(_SIMPLE_STATE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        deleted += 1
        print(f"RECEIVER-SIMPLE-DELETED {stamp} subvolume_id={expected['Subvolume ID']}", flush=True)
    print(f"RECEIVER-SIMPLE-DELETED count={deleted}")
    return deleted

def show_list(config: Config) -> None:
    complete, incomplete = managed_snapshot_sets(config)
    print("TIMESTAMP          STATE      SOURCES")
    for name, _ in complete:
        print(f"{name:18} COMPLETE   {','.join(source.name for source in config.sources)}")
    for name in sorted(incomplete, reverse=True):
        print(f"{name:18} INCOMPLETE {','.join(sorted(incomplete[name]))}")


def qgroup_status(path: Path, *, timeout_seconds: int = 8, warning_threshold: int = 100) -> list[str]:
    """Best-effort, bounded, read-only qgroup summary for the status command."""
    try:
        result = subprocess.run(
            ["btrfs", "qgroup", "show", str(path)],
            capture_output=True, text=True, timeout=timeout_seconds, check=False,
        )
        if result.returncode != 0:
            return ["qgroups_status=unavailable;reason=query_failed;exit_code=" + str(result.returncode)]
        lines = result.stdout.splitlines()
        # btrfs-progs 5.16 uses "qgroupid rfer excl ...", while newer
        # versions use "Qgroupid Referenced Exclusive ...". Accept both,
        # but never accept arbitrary text as a successful empty inventory.
        if len(lines) < 2:
            return ["qgroups_status=unavailable;reason=unexpected_output"]
        header = lines[0].split()
        if (len(header) < 3 or header[0].lower() != "qgroupid"
                or [column.lower() for column in header[1:3]]
                not in (["rfer", "excl"], ["referenced", "exclusive"])
                or not re.fullmatch(r"[-\s]+", lines[1])
                or len(lines[1].split()) < 3):
            return ["qgroups_status=unavailable;reason=unexpected_output"]
        total = stale = under_deletion = 0
        for line in lines[2:]:
            parts = line.split()
            if not parts:
                continue
            if (len(parts) < 3 or not re.fullmatch(r"\d+/\d+", parts[0])
                    or not all(re.fullmatch(r"\d+(?:\.\d+)?(?:[KMGTPE]i?B|B)", value)
                               for value in parts[1:3])):
                return ["qgroups_status=unavailable;reason=unexpected_output"]
            total += 1
            if "<stale>" in line:
                stale += 1
            if "<under deletion>" in line:
                under_deletion += 1
        state = "warning" if stale > warning_threshold or under_deletion else "ok"
        return [f"qgroups_total={total}", f"qgroups_stale={stale}",
                f"qgroups_under_deletion={under_deletion}", f"qgroups_status={state}"]
    except subprocess.TimeoutExpired:
        return ["qgroups_status=unavailable;reason=timeout"]
    except (OSError, UnicodeError):
        return ["qgroups_status=unavailable;reason=execution_error"]


def show_status(config: Config) -> None:
    preflight(config)
    complete, incomplete = managed_snapshot_sets(config)
    print(f"snapshot_root={config.snapshot_root}")
    print(f"filesystem={filesystem_type(config.snapshot_root)}")
    for line in qgroup_status(config.snapshot_root):
        print(line)
    print(
        "retention="
        f"hourly:{config.retention.hourly},daily:{config.retention.daily},"
        f"weekly:{config.retention.weekly},monthly:{config.retention.monthly},"
        f"yearly:{config.retention.yearly},minimum_age_minutes:{config.retention.minimum_age_minutes}"
    )
    print(f"complete_timestamp_sets={len(complete)};incomplete_timestamp_sets={len(incomplete)}")
    for source in config.sources:
        print(f"source={source.name}:{source.source};managed_snapshots={len(list_managed(config, source))}")
    if config.verification.required:
        state = read_verified_diaries(config, strict=False)
        if state and "error" not in state:
            print(
                "diaries_verification=valid;"
                f"logicalDataset={state['logicalDataset']};backupId={state['backupId']};"
                f"marker={state['marker']}"
            )
        else:
            print(f"diaries_verification=not-ready;detail={(state or {}).get('error', 'unknown')}")
    else:
        print("diaries_verification=disabled")


def with_lock(path: Path, *, shared: bool = False, nonblocking: bool = True,
              require_existing: bool = False):
    if not require_existing:
        path.parent.mkdir(parents=True, exist_ok=True)
    flags_open = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    if not require_existing:
        flags_open |= os.O_CREAT
    fd = os.open(path, flags_open, 0o600)
    handle = os.fdopen(fd, "r+")
    if require_existing:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            handle.close()
            raise SnapshotError(f"unsafe existing writer lock: {path}")
    flags = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    if nonblocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(handle.fileno(), flags)
    except BlockingIOError as exc:
        handle.close()
        raise SnapshotError(f"another operation holds {path}") from exc
    return handle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/etc/btrfs-snapshot-manager.json")
    sub = parser.add_subparsers(dest="command", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--timestamp")
    prune_parser = sub.add_parser("prune")
    prune_parser.add_argument("--dry-run", action="store_true")
    prune_parser.add_argument("--max-delete", type=int, help="limit source pruning to 1..32 snapshot sets per run")
    sub.add_parser("list")
    sub.add_parser("status")
    sub.add_parser("receiver-inventory")
    sub.add_parser("receiver-plan", help="read-only retention selection for verified received snapshots")
    sub.add_parser("receiver-simple-plan", help="Btrfs-verified simplified receiver retention preview")
    simple_prune = sub.add_parser("receiver-simple-prune", help="explicitly gated simplified receiver retention")
    simple_prune.add_argument("--max-delete", type=int, required=True)
    coordination = sub.add_parser("receiver-coordination-check", help="lock-held read-only receiver parent validation; no deletion authority")
    coordination.add_argument("--snapshot", required=True)
    coordination.add_argument("--source-uuid", required=True)
    sub.add_parser("receiver-recovery-plan", help="lock-held non-mutating interrupted receiver prune classification")
    guarded = sub.add_parser("receiver-prune", help="explicitly approved, locked receiver deletion")
    guarded.add_argument("--approval-file", required=True)
    sub.add_parser("run")
    add_parser = sub.add_parser("hold-add")
    add_parser.add_argument("timestamp")
    add_parser.add_argument("--reason", required=True)
    release_parser = sub.add_parser("hold-release")
    release_parser.add_argument("timestamp")
    sub.add_parser("hold-list")
    args = parser.parse_args(argv)

    try:
        require_root()
        config = load_config(Path(args.config))
        if config.mode == "receiver" and args.command not in {"list", "status", "receiver-inventory", "receiver-plan", "receiver-prune", "receiver-coordination-check", "receiver-recovery-plan", "receiver-simple-plan", "receiver-simple-prune"}:
            raise SnapshotError("receiver mode supports only explicit receiver operations")
        manager_lock = with_lock(config.lock_path) if args.command in {"create", "prune", "run", "hold-add", "hold-release", "hold-list", "receiver-prune", "receiver-coordination-check", "receiver-recovery-plan", "receiver-inventory", "receiver-plan", "receiver-simple-plan", "receiver-simple-prune"} else None
        writer_lock = None
        try:
            if args.command in {"receiver-prune", "receiver-coordination-check", "receiver-recovery-plan", "receiver-inventory", "receiver-plan"}:
                if config.receiver_state_dir is None or config.writer_lock_path != config.receiver_state_dir / "writer.lock":
                    raise SnapshotError("receiver writer lock configuration missing or inconsistent")
                writer_lock = with_lock(config.writer_lock_path, require_existing=True)
            if args.command in {"create", "run"} and config.writer_lock_path is not None:
                writer_lock = with_lock(config.writer_lock_path, shared=True, require_existing=True)
            if args.command == "create":
                create_all(config, args.timestamp)
            elif args.command == "prune":
                prune(config, args.dry_run, args.max_delete)
            elif args.command == "list":
                show_list(config)
            elif args.command == "status":
                show_status(config)
            elif args.command == "receiver-inventory":
                receiver_inventory(config)
            elif args.command == "receiver-plan":
                receiver_plan(config)
            elif args.command == "receiver-simple-plan":
                receiver_simple_print_plan(receiver_simple_plan(config))
            elif args.command == "receiver-simple-prune":
                receiver_simple_prune(config, max_delete=args.max_delete)
            elif args.command == "receiver-coordination-check":
                receiver_coordination_check(config, args.snapshot, args.source_uuid)
            elif args.command == "receiver-recovery-plan":
                receiver_recovery_plan(config)
            elif args.command == "receiver-prune":
                receiver_guarded_prune(config, Path(args.approval_file))
            elif args.command in {"hold-add", "hold-release", "hold-list"}:
                checkpoint_command(config, args.command, getattr(args, "timestamp", None), getattr(args, "reason", None))
            elif args.command == "run":
                create_all(config)
                prune(config, False)
        finally:
            if writer_lock is not None:
                writer_lock.close()
            if manager_lock is not None:
                manager_lock.close()
        return 0
    except SnapshotError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
