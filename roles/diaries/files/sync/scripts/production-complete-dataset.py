#!/usr/bin/env python3
"""Production complete-dataset backup/restore orchestration for Diaries (0033-FEAT).

The deployed .env is the authority for production identity.  PostgreSQL remains
available while diaries-responder is quiesced.  Mutable Files bytes are accessed
through the same Docker-managed CIFS volume used by the responder; no host NAS
mount is assumed.  Complete media use the shared schema-2 helpers deployed beside
this script.  Database-only helpers remain separate and unchanged.
"""
from __future__ import annotations

import datetime as dt
import fcntl
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import sys
import time
from typing import Any, Iterable
from urllib.parse import quote

BACKUP_ID_RE = re.compile(r"^\d{8}-\d{6}Z$")
DATASET = "production"
DB_SERVICE = os.environ.get("DIARIES_DB_SERVICE", "diaries-db")
RESPONDER_SERVICE = os.environ.get("DIARIES_RESPONDER_SERVICE", "diaries-responder")
MQTT_SERVICE = os.environ.get("DIARIES_MQTT_SERVICE", "diaries-mqtt")
STAGING_NAME = ".image-staging"

class ToolError(RuntimeError):
    pass

def fail(message: str) -> None:
    raise ToolError(message)

def run(argv: list[str], *, cwd: Path | None = None, input_bytes: bytes | None = None,
        capture: bool = False, check: bool = True, pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(argv, cwd=str(cwd) if cwd else None, input=input_bytes,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None, pass_fds=pass_fds)
    if check and result.returncode != 0:
        details = ""
        if capture:
            details = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
        raise ToolError(f"command failed ({result.returncode}): {' '.join(argv)}" + (f"\n{details}" if details else ""))
    return result

def output(argv: list[str], *, cwd: Path | None = None, input_bytes: bytes | None = None,
           pass_fds: tuple[int, ...] = ()) -> str:
    return run(argv, cwd=cwd, input_bytes=input_bytes, capture=True, pass_fds=pass_fds).stdout.decode("utf-8", errors="replace").strip()

def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()

def new_backup_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%SZ")

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolError(f"cannot read JSON {path}: {exc}") from exc

def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

class Production:
    def __init__(self, script_dir: Path):
        self.script_dir = script_dir.resolve()
        self.project = self.script_dir.parent.resolve()
        self.compose = self.project / "compose.yaml"
        self.env_file = self.project / ".env"
        self.manifest_tool = self.script_dir / "complete-dataset-manifest.py"
        self.publisher_tool = self.script_dir / "complete-dataset-publisher.py"
        self.verify_tool = self.script_dir / "complete-dataset-verification.py"
        self.stage_tool = self.script_dir / "complete-dataset-restore-stage.py"
        self.postflight_tool = self.script_dir / "complete-dataset-postflight.py"
        self.db_manifest_tool = self.script_dir / "dataset-backup-manifest.py"
        for path in (self.compose, self.env_file, self.manifest_tool, self.verify_tool,
                     self.stage_tool, self.postflight_tool, self.db_manifest_tool):
            if not path.is_file():
                fail(f"required production runtime/tooling file is missing: {path}")
        self.env = self._read_env()
        self._require_env(
            "DIARIES_NAS_CONTENT_PATH",
            "DIARIES_FILES_DIR",
            "DIARIES_DB_NAME",
            "DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT",
            "DIARIES_COMPLETE_RESTORE_STATE_ROOT",
            "DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT",
            "DIARIES_COMPLETE_BACKUP_STORAGE_MODE",
        )
        self.context = read_json_from_output([
            sys.executable, str(self.db_manifest_tool), "describe", "--project-dir", str(self.project)
        ])
        self.live_rel = self._safe_live_rel()
        self.backup_root = self._configured_absolute_path("DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT")
        self.restore_root = self._configured_absolute_path("DIARIES_COMPLETE_RESTORE_STATE_ROOT")
        self.published_root = self._configured_absolute_path("DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT")
        self.storage_mode = self.env["DIARIES_COMPLETE_BACKUP_STORAGE_MODE"]
        self._validate_complete_storage_contract()
        self._validate_compose()
        self.db_container = self._service_container(DB_SERVICE, require=True)
        self.responder_container = self._service_container(RESPONDER_SERVICE, require=True, allow_stopped=True)
        self.nas_volume = self._nas_volume_name()
        self.maintenance_image = output(["docker", "inspect", "--format", "{{.Config.Image}}", self.db_container])
        if not self.maintenance_image:
            fail("could not determine maintenance image from the running database container")

    def _read_env(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for raw in self.env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    def _require_env(self, *names: str) -> None:
        missing = [name for name in names if not self.env.get(name)]
        if missing:
            fail("missing required deployed .env value(s): " + ", ".join(missing))

    def _configured_absolute_path(self, name: str) -> Path:
        value = self.env[name]
        path = Path(value)
        if not path.is_absolute():
            fail(f"{name} must be an absolute path: {value}")
        # Keep the configured entry-point name: the published root becomes a
        # symlink after first publication and the publisher requires the
        # stable `diaries-backup` path, not its current generation target.
        # abspath normalises `.`/`..` without following symlinks.
        return Path(os.path.abspath(path))

    def _validate_complete_storage_contract(self) -> None:
        allowed_modes = {"auto", "required-btrfs", "full-copy"}
        if self.storage_mode not in allowed_modes:
            fail(
                "DIARIES_COMPLETE_BACKUP_STORAGE_MODE must be one of "
                f"{', '.join(sorted(allowed_modes))}; got {self.storage_mode!r}"
            )
        roots = {
            "complete-backup repository root": self.backup_root,
            "complete-restore state root": self.restore_root,
            "complete-backup published root": self.published_root,
        }
        items = list(roots.items())
        for index, (left_name, left) in enumerate(items):
            for right_name, right in items[index + 1:]:
                if left == right:
                    fail(f"{left_name} and {right_name} must be distinct")
                if left in right.parents or right in left.parents:
                    fail(f"{left_name} and {right_name} must not contain one another")
        source_files = str(getattr(self, "context", {}).get("files_root", "")).strip()
        if source_files:
            source_path = Path(source_files)
            if source_path.is_absolute():
                source_path = source_path.resolve(strict=False)
                if self.published_root == source_path or self.published_root in source_path.parents or source_path in self.published_root.parents:
                    fail("complete-backup published root must not overlap the mutable source Files root")

    def _safe_live_rel(self) -> str:
        content = self.env["DIARIES_NAS_CONTENT_PATH"].strip("/\\")
        selector = self.env["DIARIES_FILES_DIR"]
        parts = [p for p in PurePosixPath(content.replace("\\", "/")).parts if p not in ("", "/")]
        parts.append(selector)
        if any(p in (".", "..") or not p for p in parts):
            fail("DIARIES_NAS_CONTENT_PATH/DIARIES_FILES_DIR resolves to an unsafe NAS path")
        return "/".join(parts)

    def dc(self, *args: str, capture: bool = False, check: bool = True, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        return run(["docker", "compose", "--file", str(self.compose), "--env-file", str(self.env_file), *args],
                   cwd=self.project, capture=capture, check=check, input_bytes=input_bytes)

    def dc_output(self, *args: str, input_bytes: bytes | None = None) -> str:
        return self.dc(*args, capture=True, input_bytes=input_bytes).stdout.decode("utf-8", errors="replace").strip()

    def _validate_compose(self) -> None:
        self.dc("config", "--quiet")

    def _service_container(self, service: str, *, require: bool, allow_stopped: bool = False) -> str:
        args = ["ps"]
        if allow_stopped:
            args.append("--all")
        args += ["-q", service]
        cid = self.dc_output(*args)
        if require and not cid:
            fail(f"Compose service '{service}' does not have a container; deploy/start the production stack first")
        return cid.splitlines()[0] if cid else ""

    def service_running(self, service: str) -> bool:
        cid = self._service_container(service, require=False, allow_stopped=True)
        if not cid:
            return False
        value = output(["docker", "inspect", "--format", "{{.State.Running}}", cid])
        return value.lower() == "true"

    def responder_running(self) -> bool:
        return self.service_running(RESPONDER_SERVICE)

    def stop_responder(self) -> None:
        if self.responder_running():
            self.dc("stop", RESPONDER_SERVICE)
        self.assert_responder_stopped()

    def start_responder(self) -> None:
        self.dc("up", "--detach", "--no-deps", RESPONDER_SERVICE)
        cid = self._service_container(RESPONDER_SERVICE, require=True, allow_stopped=True)
        self.wait_healthy(cid, 120)

    def assert_responder_stopped(self) -> None:
        if self.responder_running():
            fail("diaries-responder is still running; refusing durable dataset operation")

    def wait_healthy(self, cid: str, seconds: int) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            state = output(["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{if .State.Running}}running{{else}}stopped{{end}}{{end}}", cid])
            if state in ("healthy", "running"):
                return
            if state in ("unhealthy", "stopped", "exited"):
                fail(f"container {cid} did not become healthy: {state}")
            time.sleep(2)
        fail(f"timed out waiting for container health: {cid}")

    def _nas_volume_name(self) -> str:
        raw = output(["docker", "inspect", "--format", "{{json .Mounts}}", self.responder_container])
        try:
            mounts = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ToolError("could not inspect responder mounts") from exc
        for mount in mounts:
            if mount.get("Destination") == "/data/files" and mount.get("Type") == "volume" and mount.get("Name"):
                return str(mount["Name"])
        fail("could not resolve the Docker volume mounted at responder /data/files")

    def maintenance(self, shell: str, *, binds: Iterable[tuple[Path, str, bool]] = (), capture: bool = False,
                    extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
        argv = ["docker", "run", "--rm", "--mount", f"type=volume,src={self.nas_volume},dst=/nas",
                "-e", f"LIVE_REL={self.live_rel}"]
        for host, target, readonly in binds:
            spec = f"type=bind,src={host.resolve()},dst={target}"
            if readonly:
                spec += ",readonly"
            argv += ["--mount", spec]
        for key, value in (extra_env or {}).items():
            argv += ["-e", f"{key}={value}"]
        argv += [self.maintenance_image, "sh", "-ec", shell]
        return run(argv, capture=capture)

    def inspect_staging(self) -> tuple[str, int]:
        shell = r'''
root="/nas/$LIVE_REL"; stage="$root/.image-staging"
[ -d "$root" ] || { echo "ERROR: live Files root is unavailable: $root" >&2; exit 11; }
if [ ! -e "$stage" ]; then echo 'empty|0'; exit 0; fi
[ -d "$stage" ] || { echo 'ERROR: .image-staging is not a directory' >&2; exit 12; }
count="$(find "$stage" -mindepth 1 -print | wc -l | tr -d ' ')"
if [ "$count" = 0 ]; then echo 'empty|0'; exit 0; fi
if [ "$count" = 1 ] && [ -f "$stage/catalogue.lock" ] && [ ! -s "$stage/catalogue.lock" ]; then echo 'excluded-benign|1'; exit 0; fi
echo "ERROR: .image-staging contains $count unexplained entries" >&2; exit 13
'''
        result = self.maintenance(shell, capture=True)
        line = result.stdout.decode().strip().splitlines()[-1]
        disposition, count = line.split("|", 1)
        return disposition, int(count)

    def copy_live_to_host(self, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        shell = r'''
set -o pipefail
root="/nas/$LIVE_REL"
mkdir -p /out
cd "$root"
tar --exclude='./.image-staging' -cf - . | tar -C /out -xf -
# The maintenance container runs as root and tar may apply the NAS root's
# restrictive ownership/mode to the bind-mounted destination.  The backup
# media must remain readable/manageable by the operator process on the host.
rm -rf /out/.image-staging
chown -R "$HOST_UID:$HOST_GID" /out
[ ! -e /out/.image-staging ] || { echo 'ERROR: transient .image-staging leaked into host snapshot' >&2; exit 32; }
'''
        self.maintenance(
            shell,
            binds=[(destination, "/out", False)],
            extra_env={"HOST_UID": str(os.getuid()), "HOST_GID": str(os.getgid())},
        )

    def incremental_capture_preflight(self) -> None:
        """Fail closed: the deployed maintenance image must already contain rsync."""
        self.maintenance('command -v rsync >/dev/null 2>&1 && rsync --version >/dev/null')

    def incremental_capture_files(self, partial: Path, previous: Path) -> None:
        """Transfer only changed NAS Files into a private empty workspace.

        Previous is read-only at the container mount; rsync --link-dest only
        shares regular files whose checksum and attributes agree. No source
        path or existing generation is used as a writable destination.
        """
        shell = r''' 
set -eu
root="/nas/$LIVE_REL"
[ -d "$root" ] || { echo 'NAS Files root missing' >&2; exit 41; }
# Reject links and special entries rather than following them across mounts.
if find "$root" -path "$root/.image-staging" -prune -o \
    ! -type f ! -type d -print | grep -q .; then
    echo 'NAS Files contains a symlink or special entry' >&2; exit 42
fi
# --checksum prevents false reuse where content changed but size/time did not.
# Exclude volatile stage on both transfer and the post-transfer comparison.
rsync -rptcog --chown="$HOST_UID:$HOST_GID" --exclude='/.image-staging/' \
    --link-dest=/previous/files/ "$root/" /backup/files/
# Directories have independent inodes; regular Files may be shared.
# Only adjust directory ownership, NEVER run recursive chown/chmod here.
find /backup/files -type d -exec chown "$HOST_UID:$HOST_GID" {} +
# Independent source comparison, without constructing .source-verify.
changes="$(rsync -rptcogni --chown="$HOST_UID:$HOST_GID" --delete \
    --exclude='/.image-staging/' "$root/" /backup/files/)"
if [ -n "$changes" ]; then
    echo "NAS-to-candidate mismatch: $changes" >&2; exit 43
fi
[ ! -e /backup/files/.image-staging ] || exit 44
'''
        self.maintenance(shell, binds=[(partial, "/backup", False), (previous, "/previous", True)],
                         extra_env={"HOST_UID": str(os.getuid()), "HOST_GID": str(os.getgid())})

    def copy_backup_to_stage(self, backup: Path, stage_rel: str) -> None:
        shell = r'''
set -o pipefail
live="/nas/$LIVE_REL"; parent="$(dirname "$live")"; stage="$parent/$STAGE_LEAF"
[ ! -e "$stage" ] || { echo "ERROR: restore stage already exists: $stage" >&2; exit 21; }
mkdir -p "$stage"
tar -C /backup/files -cf - . | tar -C "$stage" -xf -
'''
        self.maintenance(shell, binds=[(backup, "/backup", True)], extra_env={"STAGE_LEAF": Path(stage_rel).name})

    def copy_nas_rel_to_host(self, rel: str, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=False)
        shell = r'''
set -o pipefail
root="/nas/$SOURCE_REL"
[ -d "$root" ] || { echo "ERROR: NAS source tree unavailable: $root" >&2; exit 31; }
tar -C "$root" -cf - . | tar -C /out -xf -
'''
        self.maintenance(shell, binds=[(destination, "/out", False)], extra_env={"SOURCE_REL": rel})

    def swap_stage_into_live(self, stage_rel: str, rollback_rel: str) -> None:
        shell = r'''
live="/nas/$LIVE_REL"; stage="/nas/$STAGE_REL"; rollback="/nas/$ROLLBACK_REL"
[ -d "$live" ] || { echo "ERROR: live Files root missing" >&2; exit 41; }
[ -d "$stage" ] || { echo "ERROR: staged Files root missing" >&2; exit 42; }
[ ! -e "$rollback" ] || { echo "ERROR: rollback Files path already exists" >&2; exit 43; }
mv "$live" "$rollback"
mv "$stage" "$live"
mkdir -p "$live/.image-staging"
'''
        self.maintenance(shell, extra_env={"STAGE_REL": stage_rel, "ROLLBACK_REL": rollback_rel})

    def rollback_files(self, rollback_rel: str, failed_rel: str) -> None:
        shell = r'''
live="/nas/$LIVE_REL"; rollback="/nas/$ROLLBACK_REL"; failed="/nas/$FAILED_REL"
[ -d "$rollback" ] || { echo "ERROR: rollback Files tree missing" >&2; exit 51; }
[ ! -e "$failed" ] || { echo "ERROR: failed-restore preservation path already exists" >&2; exit 52; }
if [ -e "$live" ]; then mv "$live" "$failed"; fi
mv "$rollback" "$live"
mkdir -p "$live/.image-staging"
'''
        self.maintenance(shell, extra_env={"ROLLBACK_REL": rollback_rel, "FAILED_REL": failed_rel})

    def db_credentials(self) -> tuple[str, str]:
        name = self.dc_output("exec", "-T", DB_SERVICE, "printenv", "POSTGRES_DB")
        user = self.dc_output("exec", "-T", DB_SERVICE, "printenv", "POSTGRES_USER")
        if not name or not user:
            fail("POSTGRES_DB/POSTGRES_USER are unavailable from the production database service")
        return name, user

    def assert_db_ready(self) -> tuple[str, str]:
        if not self.service_running(DB_SERVICE):
            fail("PostgreSQL service must remain running during complete-dataset operations")
        name, user = self.db_credentials()
        self.dc("exec", "-T", DB_SERVICE, "pg_isready", "--username", user, "--dbname", name)
        return name, user

    def psql(self, sql: str, *, database: str | None = None) -> str:
        name, user = self.db_credentials()
        return self.dc_output("exec", "-T", DB_SERVICE, "psql", "--no-psqlrc", "-At",
                              "--username", user, "--dbname", database or name,
                              "--set", "ON_ERROR_STOP=1", "--command", sql)

    def image_count(self) -> int:
        value = self.psql("SELECT count(*) FROM public.image;").strip()
        if not value.isdigit():
            fail(f"could not determine Image row count: {value!r}")
        return int(value)

    def db_snapshot(self) -> dict[str, int]:
        name, _ = self.db_credentials()
        escaped = name.replace("'", "''")
        oid = self.psql(f"SELECT oid FROM pg_database WHERE datname = '{escaped}';", database="postgres").strip()
        if not oid.isdigit():
            fail(f"could not determine database OID: {oid!r}")
        return {"oid": int(oid), "imageRowCount": self.image_count()}

    def pg_restore_list(self, dump: Path) -> None:
        data = dump.read_bytes()
        self.dc("exec", "-T", DB_SERVICE, "pg_restore", "--list", input_bytes=data)

    def restore_database(self, dump: Path) -> None:
        name, user = self.assert_db_ready()
        self.pg_restore_list(dump)
        self.dc("exec", "-T", DB_SERVICE, "dropdb", "--force", "--if-exists", "--username", user, name)
        self.dc("exec", "-T", DB_SERVICE, "createdb", "--username", user, "--owner", user, name)
        self.dc("exec", "-T", DB_SERVICE, "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges",
                "--username", user, "--dbname", name, input_bytes=dump.read_bytes())

    def manifest_verify(self, backup: Path, *, allow_partial: bool = False) -> dict[str, Any]:
        argv = [sys.executable, str(self.manifest_tool), "verify", "--backup-dir", str(backup)]
        if allow_partial:
            argv.append("--allow-partial-workspace")
        run(argv)
        manifest = read_json(backup / "dataset-manifest.json")
        return manifest

    def assert_target_matches(self, manifest: dict[str, Any]) -> None:
        expected = {
            "logicalDataset": DATASET,
            "database.storageIdentity": self.context["database_data"],
            "database.name": self.context["database_name"],
            "files.selector": self.context["files_dir"],
            "files.resolvedPhysicalRoot": self.context["files_root"],
        }
        actual = {
            "logicalDataset": manifest.get("logicalDataset"),
            "database.storageIdentity": manifest.get("database", {}).get("storageIdentity"),
            "database.name": manifest.get("database", {}).get("name"),
            "files.selector": manifest.get("files", {}).get("selector"),
            "files.resolvedPhysicalRoot": manifest.get("files", {}).get("resolvedPhysicalRoot"),
        }
        mismatches = [f"{key}: backup={actual[key]!r}, current={value!r}" for key, value in expected.items() if actual[key] != value]
        if mismatches:
            fail("complete backup target identity mismatch; refusing restore: " + "; ".join(mismatches))

    def verify_tree_against_backup(self, backup: Path, nas_rel: str, scratch_parent: Path, *, allow_staging: bool) -> tuple[int, int]:
        scratch = scratch_parent / f"verify-{int(time.time() * 1000)}"
        try:
            self.copy_nas_rel_to_host(nas_rel, scratch)
            argv = [sys.executable, str(self.stage_tool), "--backup-dir", str(backup), "--staged-files-root", str(scratch)]
            if allow_staging:
                argv.append("--allow-benign-runtime-staging")
            run(argv)
            manifest = read_json(backup / "dataset-manifest.json")
            return int(manifest["files"]["snapshot"]["fileCount"]), int(manifest["files"]["snapshot"]["totalBytes"])
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def rel_sibling(self, leaf: str) -> str:
        parent = str(PurePosixPath(self.live_rel).parent)
        return str(PurePosixPath(parent) / leaf)

    def resolved_unc_sibling(self, leaf: str) -> str:
        current = self.context["files_root"].rstrip("/\\")
        parent = current.rsplit("/", 1)[0]
        return f"{parent}/{leaf}"

def read_json_from_output(argv: list[str]) -> dict[str, Any]:
    text = output(argv)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(f"helper did not return JSON: {' '.join(argv)}") from exc
    if not isinstance(value, dict):
        fail("helper JSON result must be an object")
    return value

def validate_backup_id(value: str) -> str:
    if not BACKUP_ID_RE.fullmatch(value):
        fail(f"invalid backup ID: {value!r}; expected UTC YYYYMMDD-HHmmssZ")
    return value

def _prepared_restore_source(p: Production, backup_id: str) -> Path | None:
    """Return the exact source pinned by an existing prepared restore, if any.

    Step 7 compatibility matters for fixed publication and snapshot paths: the
    public ``diaries-backup`` pointer may advance after ``prepare`` and a
    snapshot path may live outside the legacy repository.  Continuation by
    backup ID therefore reuses the immutable directory recorded in restore
    state instead of silently resolving the ID to different media.
    """
    state_file = p.restore_root / f"{backup_id}.prepared" / "restore-state.json"
    if not state_file.is_file():
        return None
    state = read_json(state_file)
    source = state.get("restoreSource", {})
    if source.get("backupId") != backup_id:
        fail("prepared restore state backup ID does not match its directory name")
    directory = source.get("directory")
    if not isinstance(directory, str) or not directory:
        fail("prepared restore state does not contain a pinned restore source directory")
    try:
        backup = Path(directory).resolve(strict=True)
    except OSError as exc:
        raise ToolError(f"prepared restore source is unavailable: {directory}: {exc}") from exc
    if not backup.is_dir():
        fail(f"prepared restore source is not a directory: {backup}")
    return backup


def resolve_backup(p: Production, value: str, *, prefer_prepared: bool = False) -> Path:
    """Resolve legacy, fixed-current, explicit-directory and prepared sources.

    Accepted operator selectors are:
      * ``<backup-id>`` for the historical repository layout;
      * ``diaries-backup`` (or ``diaries-backup/``) for the separately configured
        stable published current dataset;
      * an explicit directory path, including a read-only path returned by
        0035 ``diaries-backup-history path``.

    For apply/rollback/postflight, a bare backup ID first resolves through the
    prepared restore state so continuation remains pinned to the exact source
    used by ``prepare`` even if the fixed current pointer has since advanced.
    """
    raw = value.strip()
    if not raw:
        fail("restore source must not be empty")
    normalised = raw.rstrip("/\\")

    if normalised == "diaries-backup":
        backup = p.published_root.resolve()
    else:
        candidate = Path(raw)
        if candidate.is_absolute() or "/" in raw or "\\" in raw:
            backup = candidate.resolve()
        else:
            backup_id = validate_backup_id(raw)
            if prefer_prepared:
                prepared = _prepared_restore_source(p, backup_id)
                if prepared is not None:
                    backup = prepared
                else:
                    backup = (p.backup_root / backup_id).resolve()
            else:
                backup = (p.backup_root / backup_id).resolve()

    if not backup.is_dir():
        fail(f"complete backup directory not found: {backup}")
    if backup.name.startswith(".") or backup.name.endswith(".partial"):
        fail("partial complete-backup workspaces are not restorable")
    return backup

def validate_sql_dump(path: Path) -> None:
    raw = path.read_bytes()
    if not raw or b"\x00" in raw or b"PostgreSQL database dump" not in raw[:8192] or b"PostgreSQL database dump complete" not in raw[-16384:]:
        fail(f"plain SQL dump is not a complete readable PostgreSQL pg_dump: {path}")

def inspect_repository_capability(repository: Path, mode: str) -> dict[str, Any]:
    """Probe at the real repository, never in /tmp or a different mount.

    A negative/indeterminate capability must never imply reflink support.
    Probe scratch is unique and cleaned automatically; completed media are untouched.
    """
    if mode not in {"auto", "required-btrfs", "full-copy"}:
        fail(f"unsupported complete-backup storage mode: {mode!r}")
    root = repository.resolve(strict=False)
    mount = "unknown"
    fstype = "unknown"
    free = "unknown"
    total = "unknown"
    supported = False
    reason = "not probed (full-copy explicitly requested)" if mode == "full-copy" else "not tested"
    if root.is_dir():
        try:
            result = subprocess.run(["findmnt", "-T", str(root), "-n", "-o", "TARGET,FSTYPE"],
                                    capture_output=True, text=True, check=True)
            mount, fstype = result.stdout.strip().rsplit(maxsplit=1)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            reason = f"cannot determine repository filesystem: {exc}"
        try:
            usage = shutil.disk_usage(root)
            free, total = str(usage.free), str(usage.total)
        except OSError as exc:
            if mode != "full-copy":
                reason = f"cannot determine filesystem space: {exc}"
        if mode != "full-copy" and fstype == "btrfs":
            try:
                with tempfile.TemporaryDirectory(prefix=".diaries-reflink-probe-", dir=root) as tmp:
                    source = Path(tmp) / "source"
                    clone = Path(tmp) / "clone"
                    source.write_bytes(b"diaries-reflink-capability-probe\n")
                    result = subprocess.run(["cp", "--reflink=always", "--", str(source), str(clone)],
                                            capture_output=True, text=True, check=False)
                    if result.returncode == 0 and clone.read_bytes() == source.read_bytes():
                        supported = True
                        reason = "Btrfs and real cp --reflink=always clone succeeded"
                    else:
                        reason = f"reflink probe failed: {result.stderr.strip() or 'clone verification failed'}"
            except (OSError, subprocess.SubprocessError) as exc:
                reason = f"reflink probe failed: {exc}"
        elif mode != "full-copy" and fstype != "unknown":
            reason = f"repository filesystem is {fstype}, not btrfs"
    else:
        reason = "repository directory does not exist"
    if mode == "required-btrfs" and not supported:
        fail(f"required-btrfs capability not proven at {root}: {reason}")
    return {"path": str(root), "mount": mount, "filesystem": fstype,
            "free_bytes": free, "total_bytes": total, "reflink": supported,
            "reason": reason, "strategy": "reflink" if supported else "full-copy"}


@contextmanager
def incremental_generation_transaction(p: Production):
    """Pin the generation across source selection, capture and publication.

    Use the publisher's existing lock; never introduce a second lock order.
    The lock file must reside next to the stable published pointer.
    """
    parent = p.published_root.parent
    if not parent.is_dir() or parent.is_symlink():
        fail("unsafe published parent for 0036 transaction lock")
    lock_path = parent / ".diaries-backup.lock"
    if lock_path.is_symlink():
        fail("publisher lock symlink refused")
    with open(lock_path, "a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield lock.fileno()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def publisher_argv(p: Production, action: str, *extra: str, held_lock_fd: int | None = None) -> list[str]:
    args = [sys.executable, str(p.publisher_tool), "--published-root", str(p.published_root),
            "--manifest-tool", str(p.manifest_tool)]
    if held_lock_fd is not None:
        args += ["--held-lock-fd", str(held_lock_fd)]
    return args + [action, *extra]


def backup_complete(p: Production, *, preflight: bool, requested_id: str | None = None, rolling: bool = False, incremental: bool = False, held_lock_fd: int | None = None) -> Path | None:
    capability = inspect_repository_capability(p.backup_root, p.storage_mode)
    db_name, db_user = p.assert_db_ready()
    staging_disposition, staging_count = p.inspect_staging()
    was_running = p.responder_running()
    backup_id = validate_backup_id(requested_id) if requested_id else new_backup_id()
    if not preflight:
        p.backup_root.mkdir(parents=True, exist_ok=True)
    partial = p.backup_root / f".{backup_id}.partial"
    final = p.backup_root / backup_id
    if partial.exists() or final.exists():
        fail(f"backup ID already exists: {backup_id}")
    print("Diaries production complete-dataset backup preflight")
    print(f"  Logical dataset:    {DATASET}")
    print(f"  Database identity:  {p.context['database_data']} / {db_name}")
    print(f"  Files selector:     {p.context['files_dir']}")
    print(f"  Files root:         {p.context['files_root']}")
    print(f"  Backup repository:  {p.backup_root}")
    print(f"  Published root:     {p.published_root}")
    print(f"  Restore state root: {p.restore_root}")
    print(f"  Storage mode:       {p.storage_mode}")
    print(f"  Repository mount:   {capability['mount']}")
    print(f"  Filesystem:         {capability['filesystem']}")
    print(f"  Free/total bytes:   {capability['free_bytes']} / {capability['total_bytes']}")
    print(f"  Reflink probe:      {capability['reason']}")
    print(f"  Effective strategy: {capability['strategy']}")
    print(f"  Docker NAS volume:  {p.nas_volume}")
    print(f"  Responder running:  {was_running}")
    print(f"  Staging:            {staging_disposition} ({staging_count} entries)")
    print(f"  Candidate:          {partial}")
    if preflight:
        print("\nPREFLIGHT OK: no writer was stopped and no backup workspace was created.")
        return None

    if capability["strategy"] == "reflink":
        fail("reflink selected, but reflink Files capture is not implemented until 0034 Step 4; "
             "use storage mode full-copy for production backup in the interim")
    prior_incremental = None
    if incremental:
        if not rolling:
            fail("incremental NAS capture requires DIARIES_0036_ROLLING_ENABLED=true")
        if not p.published_root.is_symlink():
            fail("incremental NAS capture requires an existing published generation")
        if held_lock_fd is None:
            fail("0036 incremental NAS capture requires the transaction lock")
        run(publisher_argv(p, "verify-current", held_lock_fd=held_lock_fd),
            pass_fds=(held_lock_fd,))
        prior_incremental = p.published_root.resolve(strict=True)
        p.incremental_capture_preflight()
    started = iso_now()
    stopped_by_backup = False
    partial.mkdir(parents=True)
    try:
        if was_running:
            p.stop_responder(); stopped_by_backup = True
        else:
            p.assert_responder_stopped()
        staging_disposition, staging_count = p.inspect_staging()
        (partial / "database").mkdir()
        (partial / "files").mkdir()
        capture_state = {
            "schemaVersion": 1, "feature": "0033-FEAT", "launchMode": "production",
            "backupId": backup_id, "startedAt": started,
            "writer": {"service": RESPONDER_SERVICE, "wasRunning": was_running, "stoppedByBackup": stopped_by_backup},
            "staging": {"disposition": staging_disposition, "entryCount": staging_count},
        }
        write_json(partial / "capture-state.json", capture_state)
        custom = partial / "database" / "diaries.dump"
        sql = partial / "database" / "diaries.sql"
        with custom.open("wb") as handle:
            result = subprocess.run(["docker", "compose", "--file", str(p.compose), "--env-file", str(p.env_file),
                                     "exec", "-T", DB_SERVICE, "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                                     "--username", db_user, "--dbname", db_name], cwd=p.project, stdout=handle)
            if result.returncode != 0:
                fail("custom-format pg_dump failed")
        with sql.open("wb") as handle:
            result = subprocess.run(["docker", "compose", "--file", str(p.compose), "--env-file", str(p.env_file),
                                     "exec", "-T", DB_SERVICE, "pg_dump", "--format=plain", "--no-owner", "--no-privileges",
                                     "--username", db_user, "--dbname", db_name], cwd=p.project, stdout=handle)
            if result.returncode != 0:
                fail("plain SQL pg_dump failed")
        p.pg_restore_list(custom)
        validate_sql_dump(sql)
        if incremental:
            p.incremental_capture_files(partial, prior_incremental)
            # The independent NAS-side rsync checksum comparison replaces the
            # expensive second full capture. The verifier still produces the
            # schema-2-compatible captured-files inventory and checks DB dumps.
            run([sys.executable, str(p.verify_tool), "--backup-dir", str(partial),
                 "--source-files-root", str(partial / "files")])
        else:
            shell = r'''
    set -o pipefail
    root="/nas/$LIVE_REL"
    cd "$root"
    tar --exclude='./.image-staging' -cf - . | tar -C /backup/files -xf -
    # Extraction is performed by a root maintenance container.  Normalise the
    # host-side ownership back to the invoking operator so the Python verifier and
    # later operators can traverse/manage the complete backup media.
    rm -rf /backup/files/.image-staging
    chown -R "$HOST_UID:$HOST_GID" /backup/files
    [ ! -e /backup/files/.image-staging ] || { echo 'ERROR: transient .image-staging leaked into captured Files snapshot' >&2; exit 33; }
    '''
            p.maintenance(
                shell,
                binds=[(partial, "/backup", False)],
                extra_env={"HOST_UID": str(os.getuid()), "HOST_GID": str(os.getgid())},
            )
            source_verify = partial / ".source-verify"
            p.copy_live_to_host(source_verify)
            try:
                run([sys.executable, str(p.verify_tool), "--backup-dir", str(partial), "--source-files-root", str(source_verify)])
            finally:
                shutil.rmtree(source_verify, ignore_errors=True)
            if rolling and p.published_root.is_symlink():
                # Verify and pin the existing generation before reusing immutable
                # inodes. Strict opt-in: any failure leaves capture unpublished.
                prior = p.published_root.resolve(strict=True)
                run(publisher_argv(p, "verify-current", held_lock_fd=held_lock_fd),
                    pass_fds=(held_lock_fd,) if held_lock_fd is not None else ())
                run([sys.executable, str(p.script_dir / "rolling-files-reuse.py"),
                     "--candidate", str(partial), "--previous", str(prior),
                     "--manifest-tool", str(p.manifest_tool)])
        image_count = p.image_count()
        runtime_images = [line for line in p.dc_output("config", "--images").splitlines() if line.strip()]
        application_identity = json.dumps({"runtimeImages": runtime_images}, separators=(",", ":"))
        import base64
        identity_b64 = base64.b64encode(application_identity.encode()).decode()
        completed = iso_now()
        run([sys.executable, str(p.manifest_tool), "write", "--backup-dir", str(partial),
             "--logical-dataset", DATASET, "--launch-mode", "production", "--known-consumer", "production",
             "--database-storage-identity", p.context["database_data"], "--database-name", db_name,
             "--files-selector", p.context["files_dir"], "--files-root", p.context["files_root"],
             "--application-identity-base64", identity_b64,
             "--writer-method", "docker-compose-service-stop",
             "--writer", f"docker:production/{RESPONDER_SERVICE}",
             "--writer-evidence", f"{RESPONDER_SERVICE} stopped/rechecked before capture; PostgreSQL remained running",
             "--image-row-count", str(image_count), "--catalogued-file-count", str(image_count),
             "--staging-disposition", staging_disposition, "--staging-entry-count", str(staging_count),
             "--staging-note", "transient .image-staging excluded from complete Files snapshot",
             "--started-at", started, "--completed-at", completed])
        p.manifest_verify(partial, allow_partial=True)
        os.replace(partial, final)
        p.manifest_verify(final)
        if was_running:
            p.start_responder()
        print("\nCOMPLETE DATASET BACKUP COMPLETE.")
        print(f"  Final backup:       {final}")
        print("  Database dumps:     database/diaries.dump + database/diaries.sql")
        print("  Durable Files:      files/ (transient .image-staging excluded)")
        print("  Manifest:           schema-2 dataset-manifest.json verified")
        print(f"  Prior writer state: {'restored' if was_running else 'remained stopped'}")
        return final
    except Exception:
        print(f"ERROR: backup failed; incomplete media, if present, remains non-restorable at {partial}", file=sys.stderr)
        print("ERROR: responder is deliberately left stopped after a failed capture/finalisation.", file=sys.stderr)
        try:
            p.stop_responder()
        except Exception:
            pass
        raise

def publisher_preflight(p: Production) -> None:
    if not p.publisher_tool.is_file():
        fail(f"required production publisher is missing: {p.publisher_tool}")
    run([
        sys.executable, str(p.publisher_tool),
        "--published-root", str(p.published_root),
        "--manifest-tool", str(p.manifest_tool),
        "preflight",
    ])


def publish_completed_backup(p: Production, backup: Path, *, rolling: bool = False,
                             held_lock_fd: int | None = None) -> None:
    """Publish one already-completed legacy schema-2 backup as stable current.

    Publication is deliberately after successful immutable legacy capture.  If
    publication fails, the timestamp-ID backup remains valid and the publisher
    contract preserves the previously selected stable generation.
    """
    if not p.publisher_tool.is_file():
        fail(f"required production publisher is missing: {p.publisher_tool}")
    pass_fds = (held_lock_fd,) if held_lock_fd is not None else ()
    run(publisher_argv(p, "create-linked" if rolling else "create", str(backup),
                       held_lock_fd=held_lock_fd), pass_fds=pass_fds)
    run(publisher_argv(p, "verify-current", held_lock_fd=held_lock_fd),
        pass_fds=pass_fds)
    selected = output(publisher_argv(p, "show-current-id", held_lock_fd=held_lock_fd),
                      pass_fds=pass_fds)
    if selected != backup.name:
        fail(
            "publication verification selected an unexpected backup ID: "
            f"expected {backup.name}, got {selected!r}"
        )
    print("\nCOMPLETE DATASET PUBLICATION COMPLETE.")
    print(f"  Stable path:        {p.published_root}")
    print(f"  Published backup:   {selected}")
    print(f"  Legacy backup kept: {backup}")


def preflight_restore(p: Production, backup: Path) -> tuple[dict[str, Any], str, str]:
    manifest = p.manifest_verify(backup)
    p.assert_target_matches(manifest)
    p.assert_db_ready()
    p.pg_restore_list(backup / "database" / "diaries.dump")
    validate_sql_dump(backup / "database" / "diaries.sql")
    disposition, count = p.inspect_staging()
    backup_id = str(manifest["backupId"])
    stage_rel = p.rel_sibling(f".{p.context['files_dir']}.restore-{backup_id}.staged")
    rollback_rel = p.rel_sibling(f".{p.context['files_dir']}.pre-restore-{backup_id}.rollback")
    print("Diaries production complete-dataset restore preflight")
    print(f"  Logical dataset:    {DATASET}")
    print(f"  Restore source:     {backup}")
    print(f"  Database target:    {p.context['database_data']} / {p.context['database_name']}")
    print(f"  Files target:       {p.context['files_dir']} -> {p.context['files_root']}")
    print(f"  Backup repository:  {p.backup_root}")
    print(f"  Published root:     {p.published_root}")
    print(f"  Restore state root: {p.restore_root}")
    print(f"  Storage mode:       {p.storage_mode}")
    print(f"  Files in backup:    {manifest['files']['snapshot']['fileCount']} / {manifest['files']['snapshot']['totalBytes']} bytes")
    print(f"  Target staging:     {disposition} ({count} entries)")
    print(f"  Replacement stage: {p.resolved_unc_sibling(Path(stage_rel).name)}")
    print(f"  Responder running:  {p.responder_running()}")
    return manifest, stage_rel, rollback_rel

def state_paths(p: Production, backup_id: str) -> tuple[Path, Path]:
    directory = p.restore_root / f"{backup_id}.prepared"
    return directory, directory / "restore-state.json"

def prepare_restore(p: Production, backup: Path) -> None:
    manifest, stage_rel, rollback_rel = preflight_restore(p, backup)
    backup_id = str(manifest["backupId"])
    state_dir, state_file = state_paths(p, backup_id)
    if state_dir.exists():
        fail(f"prepared restore state already exists: {state_dir}")
    answer = input("\nType RESTORE to prepare this complete-dataset restore: ")
    if answer != "RESTORE":
        fail("restore preparation cancelled: exact RESTORE token was not supplied")
    prior_running = p.responder_running()
    p.stop_responder()
    disposition, count = p.inspect_staging()
    state_dir.mkdir(parents=True)
    safety_id = new_backup_id()
    while (p.backup_root / safety_id).exists() or (p.backup_root / f".{safety_id}.partial").exists():
        time.sleep(1); safety_id = new_backup_id()
    print(f"\nCreating mandatory pre-restore COMPLETE DATASET safety backup: {safety_id}")
    safety = backup_complete(p, preflight=False, requested_id=safety_id)
    assert safety is not None
    p.manifest_verify(safety)
    p.copy_backup_to_stage(backup, stage_rel)
    count_files, total_bytes = p.verify_tree_against_backup(backup, stage_rel, state_dir, allow_staging=False)
    state = {
        "schemaVersion": 1, "feature": "0033-FEAT", "step": 5, "status": "prepared-awaiting-apply",
        "restoreSource": {"backupId": backup_id, "directory": str(backup), "manifestValidated": True},
        "target": {"logicalDataset": DATASET, "databaseStorageIdentity": p.context["database_data"],
                   "databaseName": p.context["database_name"], "filesSelector": p.context["files_dir"],
                   "resolvedFilesRoot": p.context["files_root"], "nasVolume": p.nas_volume, "liveRelative": p.live_rel},
        "priorWriter": {"service": RESPONDER_SERVICE, "wasRunning": prior_running, "quiesced": True},
        "targetStaging": {"disposition": disposition, "entryCount": count, "recheckedAfterQuiescence": True},
        "safetyBackup": {"required": True, "backupId": safety_id, "directory": str(safety), "verified": True},
        "stagedFiles": {"relative": stage_rel, "resolved": p.resolved_unc_sibling(Path(stage_rel).name),
                        "copied": True, "inventoryVerified": True, "fileCount": count_files, "totalBytes": total_bytes},
        "rollback": {"relative": rollback_rel, "resolved": p.resolved_unc_sibling(Path(rollback_rel).name),
                     "status": "available-after-apply", "automaticRollbackAvailable": True},
        "liveDataset": {"databaseChanged": False, "filesRootChanged": False},
        "preparedAt": iso_now(), "failure": None,
    }
    write_json(state_file, state)
    print("\nPRODUCTION RESTORE PREPARATION COMPLETE.")
    print(f"  Safety backup:      {safety}")
    print(f"  Staged replacement: {state['stagedFiles']['resolved']}")
    print(f"  Prepared state:     {state_file}")
    print("  Live database:      UNCHANGED")
    print("  Live Files root:    UNCHANGED")
    print("  Responder:          STOPPED pending apply/postflight")

def load_state(p: Production, backup: Path) -> tuple[dict[str, Any], Path, Path]:
    manifest = p.manifest_verify(backup)
    p.assert_target_matches(manifest)
    backup_id = str(manifest["backupId"])
    state_dir, state_file = state_paths(p, backup_id)
    if not state_file.is_file():
        fail(f"prepared restore state is missing: {state_file}")
    state = read_json(state_file)
    if state.get("feature") != "0033-FEAT" or state.get("restoreSource", {}).get("backupId") != backup_id:
        fail("prepared restore state does not match selected complete backup")
    recorded_source = state.get("restoreSource", {}).get("directory")
    if not isinstance(recorded_source, str) or not recorded_source:
        fail("prepared restore state does not contain its pinned restore source directory")
    try:
        recorded_path = Path(recorded_source).resolve(strict=True)
    except OSError as exc:
        raise ToolError(f"prepared restore source is unavailable: {recorded_source}: {exc}") from exc
    if recorded_path != backup.resolve():
        fail(f"selected restore source does not match the source pinned by prepare: {recorded_path}")
    if state.get("target", {}).get("filesSelector") != p.context["files_dir"] or state.get("target", {}).get("resolvedFilesRoot") != p.context["files_root"]:
        fail("prepared restore target no longer matches deployed .env Files identity")
    safety = Path(str(state.get("safetyBackup", {}).get("directory", "")))
    if not state.get("safetyBackup", {}).get("verified") or not safety.is_dir():
        fail("prepared restore state does not contain a verified mandatory safety backup")
    p.manifest_verify(safety)
    return state, state_dir, state_file

def apply_restore(p: Production, backup: Path) -> None:
    state, state_dir, state_file = load_state(p, backup)
    if state.get("status") not in ("prepared-awaiting-apply", "step6-apply-failed"):
        fail(f"restore state is not ready for apply: {state.get('status')}")
    p.stop_responder()
    stage_rel = str(state["stagedFiles"]["relative"])
    rollback_rel = str(state["rollback"]["relative"])
    p.verify_tree_against_backup(backup, stage_rel, state_dir, allow_staging=False)
    before = p.db_snapshot()
    print("\nDiaries production complete-dataset restore apply")
    print(f"  Restore source:      {backup}")
    print(f"  Safety backup:       {state['safetyBackup']['directory']}")
    print(f"  Database before:     OID={before['oid']}, Image rows={before['imageRowCount']}")
    print(f"  Files stage:         {state['stagedFiles']['resolved']}")
    print(f"  Files rollback path: {state['rollback']['resolved']}")
    answer = input("\nType APPLY to replace both PostgreSQL and the live Files root: ")
    if answer != "APPLY":
        fail("restore apply cancelled: exact APPLY token was not supplied")
    try:
        state["status"] = "step6-applying"; state["applyStartedAt"] = iso_now(); write_json(state_file, state)
        p.restore_database(backup / "database" / "diaries.dump")
        state["liveDataset"]["databaseChanged"] = True; write_json(state_file, state)
        p.swap_stage_into_live(stage_rel, rollback_rel)
        state["liveDataset"]["filesRootChanged"] = True; write_json(state_file, state)
        file_count, total_bytes = p.verify_tree_against_backup(backup, p.live_rel, state_dir, allow_staging=True)
        after = p.db_snapshot()
        state["step"] = 6; state["status"] = "applied-awaiting-postflight"; state["applyCompletedAt"] = iso_now()
        state["databaseBefore"] = before; state["databaseAfter"] = after
        state["appliedFiles"] = {"fileCount": file_count, "totalBytes": total_bytes, "inventoryVerified": True}
        write_json(state_file, state)
        print("\nPRODUCTION COMPLETE-DATASET APPLY COMPLETE.")
        print(f"  Database after:      OID={after['oid']}, Image rows={after['imageRowCount']}")
        print(f"  Files after:         {file_count} files / {total_bytes} bytes; exact inventory verified")
        print(f"  Rollback Files:      {state['rollback']['resolved']}")
        print(f"  Safety backup:       {state['safetyBackup']['directory']}")
        print(f"  Rollback command:    restore-dataset.sh rollback {state['restoreSource']['backupId']}")
        print("  Responder:           STOPPED - postflight must pass before prior state is restored")
    except Exception as exc:
        state["status"] = "step6-apply-failed"; state["failure"] = str(exc); write_json(state_file, state)
        try: p.stop_responder()
        except Exception: pass
        raise

def rollback_restore(p: Production, backup: Path) -> None:
    state, state_dir, state_file = load_state(p, backup)
    if state.get("status") == "restore-complete" or not state.get("rollback", {}).get("automaticRollbackAvailable", True):
        fail("automatic rollback is closed after successful postflight acceptance")
    p.stop_responder()
    safety = Path(state["safetyBackup"]["directory"])
    safety_manifest = p.manifest_verify(safety)
    p.assert_target_matches(safety_manifest)
    p.restore_database(safety / "database" / "diaries.dump")
    failed_rel = p.rel_sibling(f".{p.context['files_dir']}.failed-restore-{state['restoreSource']['backupId']}-{int(time.time())}")
    p.rollback_files(str(state["rollback"]["relative"]), failed_rel)
    file_count, total_bytes = p.verify_tree_against_backup(safety, p.live_rel, state_dir, allow_staging=True)
    state["step"] = 6; state["status"] = "rollback-complete-writers-stopped"; state["rollback"]["status"] = "completed"
    state["rollback"]["failedReplacementRelative"] = failed_rel; state["rollback"]["completedAt"] = iso_now()
    state["rollback"]["restoredFileCount"] = file_count; state["rollback"]["restoredBytes"] = total_bytes
    write_json(state_file, state)
    print("\nPRODUCTION COMPLETE-DATASET ROLLBACK COMPLETE.")
    print(f"  Safety database restored from: {safety}")
    print(f"  Pre-restore Files reinstated:   {p.context['files_root']}")
    print("  Responder:                     STOPPED for operator review")

def mqtt_payload(p: Production, topic: str) -> dict[str, Any]:
    config = read_json(p.project / "config" / "responder" / "responder.json")
    user = str(config.get("mqtt", {}).get("user", {}).get("username", ""))
    password = str(config.get("mqtt", {}).get("user", {}).get("password", ""))
    if not user or not password:
        fail("responder MQTT credentials are missing from deployed config/responder/responder.json")
    broker = p._service_container(MQTT_SERVICE, require=True, allow_stopped=True)
    raw = output(["docker", "exec", broker, "mosquitto_sub", "-h", "localhost", "-p", "1883", "-u", user, "-P", password,
                  "-t", topic, "-C", "1", "-W", "8"])
    if not raw:
        fail(f"retained MQTT payload is empty for {topic}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolError(f"retained MQTT payload is not JSON for {topic}") from exc
    if not isinstance(value, dict):
        fail(f"retained MQTT payload is not an object for {topic}")
    return value

def postflight_restore(p: Production, backup: Path) -> None:
    state, state_dir, state_file = load_state(p, backup)
    if state.get("status") not in ("applied-awaiting-postflight", "postflight-failed"):
        fail(f"restore state is not ready for postflight: {state.get('status')}")
    p.stop_responder()
    manifest = p.manifest_verify(backup)
    post_dir = state_dir / "postflight"; post_dir.mkdir(exist_ok=True)
    state["step"] = 7; state["status"] = "postflight-running"; state["postflight"] = {"startedAt": iso_now(), "status": "running"}; write_json(state_file, state)
    mirror = post_dir / "live-files-mirror"
    try:
        db = p.db_snapshot()
        if db["imageRowCount"] != int(manifest["counts"]["imageRowCount"]):
            fail(f"restored Image row count {db['imageRowCount']} does not match manifest {manifest['counts']['imageRowCount']}")
        if mirror.exists(): shutil.rmtree(mirror)
        p.copy_nas_rel_to_host(p.live_rel, mirror)
        run([sys.executable, str(p.stage_tool), "--backup-dir", str(backup), "--staged-files-root", str(mirror), "--allow-benign-runtime-staging"])
        catalogue_sql = "SELECT COALESCE(json_agg(json_build_object('id',id,'relativePath',relative_path,'checksum',checksum,'mimeType',mime_type) ORDER BY id),'[]'::json)::text FROM public.image;"
        catalogue_text = p.psql(catalogue_sql)
        catalogue_path = post_dir / "image-catalogue.json"; catalogue_path.write_text(catalogue_text + "\n", encoding="utf-8")
        report_path = post_dir / "catalogue-files-reconciliation.json"
        run([sys.executable, str(p.postflight_tool), "--files-root", str(mirror), "--catalogue-json", str(catalogue_path),
             "--expected-image-count", str(manifest["counts"]["imageRowCount"]), "--output", str(report_path)])
        report = read_json(report_path); image = report.get("representativeImage")
        if not isinstance(image, dict): fail("postflight requires a representative Image row")
        marquee = p.psql("SELECT id FROM public.marquee ORDER BY id LIMIT 1;").strip()
        if not marquee.isdigit(): fail("restored database contains no representative MARQUEE row")
        started = dt.datetime.now(dt.timezone.utc)
        p.start_responder()
        responder = p._service_container(RESPONDER_SERVICE, require=True, allow_stopped=True)
        log_result = run(["docker", "logs", "--since", started.isoformat(), responder], capture=True)
        logs = (log_result.stdout + log_result.stderr).decode("utf-8", errors="replace")
        if "synchronise: ok" not in logs:
            fail("responder startup logs do not contain 'synchronise: ok'")
        marquee_payload = mqtt_payload(p, f"diaries/marquees/{marquee}")
        if str(marquee_payload.get("id")) != marquee:
            fail("representative retained MARQUEE payload does not match restored database ID")
        image_id = str(image["id"])
        image_payload = mqtt_payload(p, f"diaries/images/{image_id}")
        if str(image_payload.get("id")) != image_id or image_payload.get("relativePath") != image.get("relativePath") or image_payload.get("checksum") != image.get("checksum"):
            fail("representative retained IMAGE payload does not match restored catalogue")
        rel_url = "/".join(quote(part, safe="") for part in str(image["relativePath"]).split("/"))
        data = run(["docker", "exec", responder, "curl", "--fail", "--silent", "--show-error", "--max-time", "15",
                    f"http://localhost:8081/files/{rel_url}"], capture=True).stdout
        if sha256_bytes(data) != image["checksum"]:
            fail("representative /files Image bytes do not match restored catalogue checksum")
        p.stop_responder()
        restored: list[str] = []
        if state.get("priorWriter", {}).get("wasRunning"):
            p.start_responder(); restored.append("docker:production/diaries-responder")
        state["status"] = "restore-complete"; state["postflight"] = {
            "startedAt": state["postflight"]["startedAt"], "completedAt": iso_now(), "status": "complete",
            "databaseVerified": True, "filesInventoryVerified": True, "catalogueReconciliationVerified": True,
            "responderHealthVerified": True, "retainedReplayVerified": True, "representativeMarqueeId": int(marquee),
            "representativeImageId": int(image_id), "representativeImagePath": image["relativePath"],
            "representativeFilesPath": f"/files/{rel_url}", "priorWriterStateRestored": True, "restoredWriters": restored,
        }
        state["rollback"]["status"] = "closed-after-postflight"; state["rollback"]["automaticRollbackAvailable"] = False; state["rollback"]["artifactsRetained"] = True
        state["failure"] = None; write_json(state_file, state)
        print("\nPRODUCTION POST-RESTORE VERIFICATION COMPLETE.")
        print(f"  Database:             queryable; Image rows={db['imageRowCount']} match manifest")
        print("  Durable Files:        exact backup inventory verified")
        print("  Catalogue/Files:      no unexplained missing/untracked/conflicting file")
        print("  Retained replay:      synchronise: ok; representative MARQUEE + IMAGE retained payloads readable")
        print(f"  /files mapping:       representative Image bytes verified at /files/{rel_url}")
        print(f"  Prior writer state:   {'restored' if restored else 'no responder was running; remains stopped'}")
        print(f"  Safety backup:        retained at {state['safetyBackup']['directory']}")
        print(f"  Pre-restore Files:    retained at {state['rollback']['resolved']}")
        print("  Automatic rollback:  closed after successful postflight acceptance")
    except Exception as exc:
        try: p.stop_responder()
        except Exception: pass
        state["status"] = "postflight-failed"; state["failure"] = str(exc)
        if isinstance(state.get("postflight"), dict): state["postflight"].update({"status": "failed", "completedAt": iso_now(), "failure": str(exc)})
        write_json(state_file, state)
        raise
    finally:
        shutil.rmtree(mirror, ignore_errors=True)

def usage() -> None:
    print("Usage:")
    print("  backup-dataset.sh [preflight|publish-preflight|publish]")
    print("  restore-dataset.sh preflight <backup-id|diaries-backup|directory>")
    print("  restore-dataset.sh prepare   <backup-id|diaries-backup|directory>")
    print("  restore-dataset.sh apply     <backup-id|diaries-backup|directory>")
    print("  restore-dataset.sh rollback  <backup-id|diaries-backup|directory>")
    print("  restore-dataset.sh postflight <backup-id|diaries-backup|directory>")

def main(argv: list[str]) -> int:
    try:
        if len(argv) < 2:
            usage(); return 2
        p = Production(Path(__file__).parent)
        group = argv[1]
        if group == "backup":
            if len(argv) == 2:
                # Frozen 0033 behaviour: create one immutable timestamp-ID backup
                # only.  Stable publication remains an explicit Step 9 action.
                backup_complete(p, preflight=False); return 0
            if len(argv) == 3 and argv[2] == "preflight":
                backup_complete(p, preflight=True); return 0
            if len(argv) == 3 and argv[2] in ("fixed-capture", "fixed-capture-preflight"):
                # 0036 replacement path: no timestamped generation or copy-based publisher.
                # Explicit opt-in. Never selected by existing production timers.
                if p.env.get("DIARIES_0036_FIXED_CAPTURE_ENABLED", "false").lower() != "true":
                    fail("fixed capture disabled: DIARIES_0036_FIXED_CAPTURE_ENABLED must be true")
                import importlib.util
                helper = p.script_dir / "fixed-dataset-capture.py"
                spec = importlib.util.spec_from_file_location("diaries_fixed_capture", helper)
                if spec is None or spec.loader is None:
                    fail("fixed capture helper cannot be loaded")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.execute(p, preflight=argv[2].endswith("preflight"))
                return 0
            if len(argv) == 3 and argv[2] == "publish-preflight":
                publisher_preflight(p)
                backup_complete(p, preflight=True)
                print("\nPUBLISH PREFLIGHT OK: publisher layout and live capture preflight both passed; no backup or publication was created.")
                return 0
            if len(argv) == 3 and argv[2] == "publish":
                # Check publication layout before quiescing the responder or
                # spending time/space on a new complete capture.
                publisher_preflight(p)
                rolling = p.env.get("DIARIES_0036_ROLLING_ENABLED", "false").lower() == "true"
                if p.env.get("DIARIES_0036_ROLLING_ENABLED", "false").lower() not in ("true", "false"):
                    fail("DIARIES_0036_ROLLING_ENABLED must be true or false")
                incremental_setting = p.env.get("DIARIES_0036_INCREMENTAL_NAS_ENABLED", "false").lower()
                if incremental_setting not in ("true", "false"):
                    fail("DIARIES_0036_INCREMENTAL_NAS_ENABLED must be true or false")
                incremental = incremental_setting == "true"
                if incremental and not rolling:
                    fail("incremental NAS capture requires rolling capture enabled")
                # All publisher operations use the same inherited FD; no lock
                # release can occur between generation selection and promotion.
                if incremental:
                    with incremental_generation_transaction(p) as held_fd:
                        backup = backup_complete(p, preflight=False, rolling=rolling,
                                                 incremental=True, held_lock_fd=held_fd)
                        if backup is None:
                            fail("internal error: completed backup path missing")
                        publish_completed_backup(p, backup, rolling=rolling, held_lock_fd=held_fd)
                else:
                    backup = backup_complete(p, preflight=False, rolling=rolling)
                    if backup is None:
                        fail("internal error: completed backup path missing")
                    publish_completed_backup(p, backup, rolling=rolling)
                return 0
            fail("backup-dataset.sh accepts no argument, 'preflight', 'publish-preflight', or 'publish'")
        if group != "restore" or len(argv) != 4:
            usage(); return 2
        action, value = argv[2], argv[3]
        if action not in {"preflight", "prepare", "apply", "rollback", "postflight"}:
            fail(f"unknown restore action: {action}")
        backup = resolve_backup(p, value, prefer_prepared=action in {"apply", "rollback", "postflight"})
        if action == "preflight":
            preflight_restore(p, backup)
            print("\nPREFLIGHT OK: no writer was stopped, no safety backup was created, and no Files staging directory was created.")
        elif action == "prepare": prepare_restore(p, backup)
        elif action == "apply": apply_restore(p, backup)
        elif action == "rollback": rollback_restore(p, backup)
        elif action == "postflight": postflight_restore(p, backup)
        return 0
    except (ToolError, OSError, ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
