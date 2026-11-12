#!/usr/bin/env python3
"""0035 Step 5: host-specific timestamp snapshot cleanup; default is dry-run."""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, check=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("mars", "pluto"), required=True)
    parser.add_argument("--config", default="/etc/btrfs-snapshot-manager.json")
    parser.add_argument("--manager", default="/usr/local/sbin/btrfs-snapshot-manager")
    parser.add_argument("--published-root", default="/home/richard/projects/diaries/data/diaries-backup")
    parser.add_argument("--apply", action="store_true", help="explicitly authorize deletion on mars ONLY")
    parser.add_argument("command", choices=("status", "dry-run", "prune"))
    args = parser.parse_args(argv)
    if args.host == "pluto":
        if args.apply:
            print("REFUSED: pluto cleanup cannot modify any files", file=sys.stderr)
            return 2
        fs = command(["findmnt", "-T", args.published_root, "-n", "-o", "FSTYPE"])
        if fs.returncode:
            print("ERROR: cannot determine pluto publication filesystem", file=sys.stderr)
            return 2
        print(f"UNSUPPORTED: pluto filesystem={fs.stdout.strip()} — no native snapshot pruning configured; no-op")
        return 0
    if args.command == "prune" and not args.apply:
        print("REFUSED: 'prune' requires --apply; use dry-run first", file=sys.stderr)
        return 2
    if args.apply and args.command != "prune":
        print("REFUSED: --apply is only permitted with prune", file=sys.stderr)
        return 2
    if not Path(args.config).is_file():
        print("ERROR: missing snapshot manager config", file=sys.stderr)
        return 2
    if not Path(args.manager).is_file():
        print("ERROR: missing snapshot manager", file=sys.stderr)
        return 2
    try:
        cfg = json.loads(Path(args.config).read_text())
        if cfg.get("snapshot_root") != "/media/usb/@snapshots" or {x.get("name") for x in cfg.get("sources", [])} != {"root", "@data"}:
            raise ValueError("unexpected mars managed sources")
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: unsafe mars config: {exc}", file=sys.stderr)
        return 2
    subcmd = ["status"] if args.command == "status" else ["prune"] + ([] if args.apply else ["--dry-run"])
    result = command([sys.executable, args.manager, "--config", args.config, *subcmd])
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
