#!/usr/bin/env python3
"""0040-FEAT Step 11: one-time checkpoint-hold migration.

Preview is read-only by default. An explicitly authorised commit writes
checkpoint holds, after guarded validation and an exclusive backup.
Never deletes Btrfs snapshots or modifies manager configuration.
"""
import argparse
import fcntl
import hashlib
import tempfile
import time
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

TIMESTAMP = re.compile(r"[0-9]{8}-[0-9]{6}Z\Z")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
EXPECTED = {
    "20261013-171228Z": "0034/0035 pre-cleanup recovery checkpoint",
    "20261018-165453Z": "Permanent 0034/0036 mango closure evidence archive",
}


class UnsafeState(Exception):
    pass


def validate_file(path):
    if path.is_symlink():
        raise UnsafeState("hold file is a symlink")
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != 0 or st.st_mode & 0o077:
        raise UnsafeState("hold file must be root-owned, mode 0600, and single-link regular")


def snapshot_uuid(path):
    result = subprocess.run(["btrfs", "subvolume", "show", str(path)], text=True, capture_output=True, check=True)
    matches = re.findall(r"^\s*UUID:\s*([0-9a-f-]{36})\s*$", result.stdout, re.M)
    if len(matches) != 1 or not UUID.fullmatch(matches[0]):
        raise UnsafeState(f"cannot uniquely identify Btrfs UUID: {path}")
    return matches[0]


def preview(document, uuid_lookup, root):
    if not isinstance(document, dict) or set(document) != {"schema", "holds"} or type(document["schema"]) is not int or document["schema"] != 1:
        raise UnsafeState("unexpected checkpoint schema")
    holds = document["holds"]
    if not isinstance(holds, dict) or set(holds) != set(EXPECTED):
        raise UnsafeState("hold timestamps differ from approved Step 11 inventory")
    migrated = {}
    for stamp, reason in EXPECTED.items():
        record = holds[stamp]
        if not TIMESTAMP.fullmatch(stamp) or not isinstance(record, dict) or set(record) != {"reason", "source_uuids"}:
            raise UnsafeState(f"invalid record for {stamp}")
        if record["reason"] != reason:
            raise UnsafeState(f"reason differs from approved inventory: {stamp}")
        ids = record["source_uuids"]
        if not isinstance(ids, dict) or set(ids) != {"root", "@data"} or any(not isinstance(x, str) or not UUID.fullmatch(x) for x in ids.values()):
            raise UnsafeState(f"unexpected source UUIDs: {stamp}")
        for name in ("root", "@data"):
            snap = root / name / stamp
            if not snap.is_dir() or snap.is_symlink():
                raise UnsafeState(f"snapshot absent or symlink: {snap}")
            actual = uuid_lookup(snap)
            if actual != ids[name]:
                raise UnsafeState(f"UUID mismatch: {snap}: expected {ids[name]}, actual {actual}")
        migrated[stamp] = {"reason": reason, "source_uuids": {"@data": ids["@data"]}}
    return {"schema": 1, "holds": migrated}




def read_candidate(holds_path, root):
    validate_file(holds_path)
    original_bytes = holds_path.read_bytes()
    raw = json.loads(original_bytes)
    proposed = preview(raw, snapshot_uuid, root)
    return original_bytes, proposed


def secure_write(path, payload):
    """Atomic, same-directory root-owned 0600 JSON write with durability."""
    fd, tempname = tempfile.mkstemp(prefix=".0040-holds-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tempname, path)
        dirfd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if os.path.exists(tempname):
            os.unlink(tempname)


def fsync_parent(path):
    fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def commit_transaction(holds, root, *, read=read_candidate, replace=secure_write,
                       before_replace=lambda: None):
    """Isolated transaction core; caller MUST hold lock and validate production gates."""
    old, proposed = read(holds, root)
    payload = (json.dumps(proposed, indent=2, sort_keys=True) + "\n").encode()
    backup = holds.with_name(".checkpoint-holds.0040-step11-before.json")
    fd = os.open(str(backup), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(old)
        out.flush()
        os.fsync(out.fileno())
    fsync_parent(backup)  # Durable rollback evidence BEFORE the original is replaced.
    before_replace()
    if holds.read_bytes() != old:
        raise UnsafeState("checkpoint hold state changed during migration")
    replace(holds, payload)
    if holds.read_bytes() != payload:
        raise UnsafeState("post-commit readback mismatch; restore backup before resuming")
    return backup, old, payload


def main():
    parser = argparse.ArgumentParser(description="0040 one-time guarded hold migration; preview by default")
    parser.add_argument("--commit", action="store_true", help="explicitly commit after independent approval")
    parser.add_argument("--authorise", default="", help="must equal 0040-STEP11-HOLDS-ONLY")
    parser.add_argument("--holds", type=Path, default=Path("/media/usb/@snapshots/.checkpoint-holds.json"))
    parser.add_argument("--snapshot-root", type=Path, default=Path("/media/usb/@snapshots"))
    parser.add_argument("--config", type=Path, default=Path("/etc/btrfs-snapshot-manager.json"))
    args = parser.parse_args()
    try:
        if os.geteuid() != 0:
            raise UnsafeState("must run as root")
        config = json.loads(args.config.read_text())
        if args.holds != Path("/media/usb/@snapshots/.checkpoint-holds.json") or args.snapshot_root != Path("/media/usb/@snapshots"):
            raise UnsafeState("nonproduction paths forbidden for commit utility")
        if config.get("mode", "source") != "source" or config.get("snapshot_root") != str(args.snapshot_root):
            raise UnsafeState("unexpected live manager configuration")
        if config.get("checkpoint_holds", {}).get("path") != str(args.holds) or config.get("checkpoint_holds", {}).get("required") is not True:
            raise UnsafeState("checkpoint hold configuration changed")
        if {s["name"] for s in config["sources"]} != {"root", "@data"}:
            raise UnsafeState("configuration already changed; refuse migration")
        if not args.commit:
            old, proposed = read_candidate(args.holds, args.snapshot_root)
            print("PREVIEW ONLY — NO FILES MODIFIED")
            print("Original sha256:", hashlib.sha256(old).hexdigest())
            print(json.dumps(proposed, indent=2, sort_keys=True))
            return 0
        if args.authorise != "0040-STEP11-HOLDS-ONLY":
            raise UnsafeState("explicit commit authorisation missing")
        if args.config.is_symlink() or args.holds.is_symlink():
            raise UnsafeState("symlink refused")
        for unit in ("btrfs-snapshot-create.timer", "btrfs-snapshot-prune.timer",
                     "btrfs-snapshot-create.service", "btrfs-snapshot-prune.service"):
            if subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0:
                raise UnsafeState(f"timer or service still active: {unit}")
        lockfd = os.open(config["lock_path"], os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            backup, old, payload = commit_transaction(args.holds, args.snapshot_root)
            print("COMMIT: hold records now @data-only; manager config MUST be switched before resuming timers")
            print("BACKUP:", backup)
            print("ORIGINAL SHA256:", hashlib.sha256(old).hexdigest())
            print("NEW SHA256:", hashlib.sha256(payload).hexdigest())
        finally:
            os.close(lockfd)
        return 0
    except (UnsafeState, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, BlockingIOError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
