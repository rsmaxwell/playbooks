#!/usr/bin/env python3
"""0033-FEAT Step 7 live Image catalogue/Files post-restore reconciliation.

This helper is intentionally read-only. The complete backup inventory is verified by
complete-dataset-restore-stage.py; this helper proves that the restored Image catalogue
still agrees with the physical mutable Files root and classifies only the reviewed
legacy Thumbs.db files as benign untracked content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

STAGING = ".image-staging"
REVIEWED_UNTRACKED_BASENAMES = {"thumbs.db"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def load_catalogue(path: Path) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"ERROR: Image catalogue JSON is unreadable: {path}: {exc}")
    if not isinstance(value, list):
        raise SystemExit("ERROR: Image catalogue JSON must be an array")
    result: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            raise SystemExit(f"ERROR: Image catalogue row {index} is not an object")
        required = ("id", "relativePath", "checksum", "mimeType")
        if any(key not in row for key in required):
            raise SystemExit(f"ERROR: Image catalogue row {index} is missing required fields")
        try:
            image_id = int(row["id"])
        except Exception:
            raise SystemExit(f"ERROR: Image catalogue row {index} has invalid id")
        rel = str(row["relativePath"])
        checksum = str(row["checksum"])
        mime = str(row["mimeType"])
        p = Path(rel)
        if image_id <= 0 or not rel or p.is_absolute() or "\\" in rel or any(part in ("", ".", "..") for part in p.parts):
            raise SystemExit(f"ERROR: Image catalogue row {index} has unsafe relativePath: {rel!r}")
        if len(checksum) != 64 or any(ch not in "0123456789abcdef" for ch in checksum):
            raise SystemExit(f"ERROR: Image catalogue row {index} has invalid SHA-256 checksum")
        result.append({"id": image_id, "relativePath": rel, "checksum": checksum, "mimeType": mime})
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-root", required=True)
    parser.add_argument("--catalogue-json", required=True)
    parser.add_argument("--expected-image-count", required=True, type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    root = Path(args.files_root).resolve()
    catalogue_path = Path(args.catalogue_json).resolve()
    output = Path(args.output).resolve()
    if not root.is_dir():
        raise SystemExit(f"ERROR: restored Files root is unavailable: {root}")

    rows = load_catalogue(catalogue_path)
    if len(rows) != args.expected_image_count:
        raise SystemExit(
            f"ERROR: Image catalogue row count {len(rows)} does not match backup manifest {args.expected_image_count}"
        )

    exact: dict[str, dict[str, Any]] = {}
    folded: dict[str, str] = {}
    for row in rows:
        rel = row["relativePath"]
        if rel in exact:
            raise SystemExit(f"ERROR: duplicate Image catalogue relativePath: {rel}")
        fold = rel.casefold()
        if fold in folded and folded[fold] != rel:
            raise SystemExit(f"ERROR: case-folding Image catalogue path conflict: {folded[fold]} vs {rel}")
        exact[rel] = row
        folded[fold] = rel

    missing: list[str] = []
    checksum_conflicts: list[str] = []
    matched = 0
    for rel, row in exact.items():
        target = (root / Path(rel)).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            raise SystemExit(f"ERROR: Image path escapes restored Files root: {rel}")
        if not target.is_file():
            missing.append(rel)
            continue
        actual = sha256(target)
        if actual != row["checksum"]:
            checksum_conflicts.append(rel)
            continue
        matched += 1

    reviewed_untracked: list[str] = []
    unexplained_untracked: list[str] = []
    physical_case: dict[str, str] = {}
    physical_files = 0
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        if current == root:
            dirnames[:] = [d for d in dirnames if d != STAGING]
        for name in filenames:
            path = current / name
            rel = canonical_rel(root, path)
            physical_files += 1
            fold = rel.casefold()
            if fold in physical_case and physical_case[fold] != rel:
                raise SystemExit(f"ERROR: case-folding physical Files conflict: {physical_case[fold]} vs {rel}")
            physical_case[fold] = rel
            if rel in exact:
                continue
            if name.casefold() in REVIEWED_UNTRACKED_BASENAMES:
                reviewed_untracked.append(rel)
            else:
                unexplained_untracked.append(rel)

    if missing or checksum_conflicts or unexplained_untracked:
        messages = []
        if missing:
            messages.append(f"missing catalogue files={len(missing)} sample={missing[:5]}")
        if checksum_conflicts:
            messages.append(f"catalogue checksum conflicts={len(checksum_conflicts)} sample={checksum_conflicts[:5]}")
        if unexplained_untracked:
            messages.append(f"unexplained untracked files={len(unexplained_untracked)} sample={unexplained_untracked[:5]}")
        raise SystemExit("ERROR: Image catalogue/Files reconciliation failed: " + "; ".join(messages))

    representative = min(rows, key=lambda row: row["id"]) if rows else None
    report = {
        "schemaVersion": 1,
        "feature": "0033-FEAT",
        "step": 7,
        "status": "ok",
        "filesRoot": str(root),
        "imageRows": len(rows),
        "cataloguedMatches": matched,
        "physicalDurableFiles": physical_files,
        "reviewedUntracked": sorted(reviewed_untracked),
        "reviewedUntrackedCount": len(reviewed_untracked),
        "unexplainedMissingCount": 0,
        "unexplainedUntrackedCount": 0,
        "checksumConflictCount": 0,
        "representativeImage": representative,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Valid restored Diaries Image catalogue / Files reconciliation")
    print(f"  Image rows:             {len(rows)}")
    print(f"  Catalogued matches:     {matched}")
    print(f"  Durable physical files: {physical_files}")
    print(f"  Reviewed untracked:     {len(reviewed_untracked)} (Thumbs.db only)")
    print("  Missing/untracked/conflicting: 0 unexplained")
    print(f"  Report:                 {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
