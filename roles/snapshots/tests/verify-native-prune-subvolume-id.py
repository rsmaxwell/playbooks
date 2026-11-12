#!/usr/bin/env python3
"""Read-only mocked regressions for native pruning identity logging."""
import contextlib
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

manager = Path(__file__).resolve().parents[1] / "files" / "btrfs-snapshot-manager.py"
spec = importlib.util.spec_from_file_location("snapshot_native_prune_test", manager)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)

path = Path("/media/usb/@snapshots/root/20261019-090008Z")
seen = []
def good_run(args, *, check=True):
    seen.append(args)
    assert args == ["btrfs", "subvolume", "show", str(path)]
    return SimpleNamespace(stdout="UUID: abc\nSubvolume ID: 20875\nFlags: readonly\n")

with patch.object(module, "run", good_run):
    assert module.native_prune_subvolume_id(path) == 20875
assert len(seen) == 1
print("PASS: parsed pre-delete Btrfs subvolume ID via read-only show")

for output in ("UUID: abc\n", "Subvolume ID: invalid\n", "Subvolume ID: 0\n",
               "Subvolume ID: 42\nSubvolume ID: 43\n"):
    with patch.object(module, "run", return_value=SimpleNamespace(stdout=output)):
        try:
            module.native_prune_subvolume_id(path)
        except module.SnapshotError:
            pass
        else:
            raise AssertionError("invalid subvolume identity accepted: " + repr(output))
print("PASS: missing, invalid and ambiguous IDs fail closed")

source = manager.read_text(encoding="utf-8")
assert 'subvolume_id = native_prune_subvolume_id(path)' in source
assert source.index('subvolume_id = native_prune_subvolume_id(path)',
                    source.index('def prune(')) < source.index('run(["btrfs", "subvolume", "delete", str(path)])',
                                                      source.index('def prune('))
assert 'print(f"DELETE {source.name} {name} subvol_id={subvolume_id} {path}", flush=True)' in source
assert 'print(f"WOULD-DELETE {source.name} {name} {snapshot_path(config, source, name)}")' in source
print("PASS: native deletion logs the verified ID before mutation; dry-run unchanged")
