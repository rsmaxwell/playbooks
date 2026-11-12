#!/usr/bin/env python3
"""Static source checks; no host access or state changes."""
from pathlib import Path
import ast
root=Path(__file__).resolve().parents[2]
manager=root/'roles/snapshots/files/btrfs-snapshot-manager.py'
text=manager.read_text()
ast.parse(text)
checks={
 'same filesystem Btrfs verification': 'source_device != root_device' in text,
 'timestamp filtering': 'parse_timestamp' in text and 'TIMESTAMP_FORMAT' in text,
 'readonly native creation': '"-r"' in text or "'-r'" in text,
 'snapshot rollback path': 'def create_all' in text and 'delete' in text,
 'set-based pruning': 'managed_snapshot_sets(config)' in text and 'if incomplete:' in text,
 'replication protection during pruning': 'pins = replication_pins(config)' in text and 'keep.update(pins)' in text,
 'checkpoint hold protection during pruning': 'holds = read_checkpoint_holds(config)' in text and 'keep.update(holds)' in text,
 'writer lock integration': 'writer_lock_path' in text,
}
for label, good in checks.items():
    print(('PASS' if good else 'FAIL') + ': ' + label)
if not all(checks.values()):
    raise SystemExit(1)
print('PASS: Step 2 preservation source contract')
