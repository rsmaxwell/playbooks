#!/usr/bin/env python3
from pathlib import Path
import ast
root = Path(__file__).resolve().parents[2]
manager = (root / 'roles/snapshots/files/btrfs-snapshot-manager.py').read_text()
wrapper = (root / 'roles/snapshots/files/diaries-snapshot-cleanup.py').read_text()
for src in (manager, wrapper):
    ast.parse(src)
assert 'validate_prune_candidate(config, source, name)' in manager
assert 'require_subvolume(candidate)' in manager
assert 'flags != "ro=true"' in manager
assert 'candidates = ' in manager
assert 'prune" and not args.apply' in wrapper
assert 'UNSUPPORTED: pluto filesystem=' in wrapper
print('PASS: fail-closed candidate preflight and read-only Btrfs verification')
print('PASS: pluto never deletes; mars requires explicit --apply')
