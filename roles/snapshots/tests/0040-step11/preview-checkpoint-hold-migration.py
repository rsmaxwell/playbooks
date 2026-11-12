#!/usr/bin/env python3
"""0040-FEAT Step 11: ONE-TIME, STRICTLY READ-ONLY checkpoint hold preview.

No modification or write operation is implemented in this tool.
Run on mars with access to root-owned checkpoint holds and Btrfs snapshots.
"""
import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--holds", type=Path, default=Path("/media/usb/@snapshots/.checkpoint-holds.json"))
    parser.add_argument("--snapshot-root", type=Path, default=Path("/media/usb/@snapshots"))
    args = parser.parse_args()
    try:
        validate_file(args.holds)
        with args.holds.open(encoding="utf-8") as f:
            raw = json.load(f)
        proposed = preview(raw, snapshot_uuid, args.snapshot_root)
        print("PREVIEW ONLY — NO FILES MODIFIED")
        print("Source checkpoint hold records verified, including both root and @data UUIDs")
        print("Proposed replacement document:")
        print(json.dumps(proposed, indent=2, sort_keys=True))
        print("PASS: safe migration preview (NOT AUTHORISED FOR COMMIT)")
        return 0
    except (UnsafeState, OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
