#!/usr/bin/env python3
"""0040 Step 5 accelerated non-destructive regression entry point.
Run with sudo to include root-only integration tests.
"""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
tests = [
    root / 'snapshots/tests/verify-0040-step04-migration.py',
    root / 'snapshots/tests/verify-0040-step05-adversarial.py',
    root / 'snapshots/tests/verify-0040-receiver-role-guard.py',
    root / 'btrfs-replication/tests/verify-step03-coordination-suite.py',
]
for test in tests:
    print(f'=== {test.name} ===', flush=True)
    result = subprocess.run([sys.executable, str(test)])
    if result.returncode != 0:
        raise SystemExit(f'FAIL: {test.name} exited {result.returncode}')
print('PASS: 0040 Step 5 accelerated non-destructive suite (root integration only if executed as root)')
