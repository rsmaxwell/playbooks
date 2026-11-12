#!/usr/bin/env python3
"""Step 6 isolated rsync/publisher-to-staged-receiver regressions."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

ROLE = Path(__file__).resolve().parents[1]
SCRIPTS = ROLE / 'files/sync/scripts'
PUBLISHER = SCRIPTS / 'complete-dataset-publisher.py'
REPLICATION = SCRIPTS / 'complete-dataset-replication.py'
fixture = Path(__file__).with_name('verify-complete-dataset-manifest.py')
namespace = {'__name__': 'fixture_support', '__file__': str(fixture)}
exec(compile(fixture.read_text().split('def mutate_manifest(')[0], str(fixture), 'exec'), namespace)

def cmd(*args, env=None):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, env=env)

def check(condition, label):
    assert condition, label
    print('PASS:', label)

with tempfile.TemporaryDirectory(prefix='0034-step6-') as tmp:
    base = Path(tmp)
    inputs = base / 'inputs'; inputs.mkdir()
    first = namespace['create_candidate'](inputs)
    check(namespace['write_manifest'](first).returncode == 0, 'schema-2 fixture built')
    bid = first.name[1:-8]
    candidate = inputs / bid; first.rename(candidate)
    public = base / 'publication' / 'diaries-backup'; public.parent.mkdir()
    check(cmd(PUBLISHER, '--published-root', public, 'create', candidate).returncode == 0, 'fixture published')
    incoming = base / 'receiver'; incoming.mkdir()
    transfer = (REPLICATION, 'transfer', '--published-root', public, '--receiver-root', incoming)
    output = cmd(*transfer)
    check(output.returncode == 0, 'pinned rsync and receiving schema-2 verification: ' + output.stderr)
    handoff = incoming / ('diaries-handoff-' + bid + '.json')
    doc = json.loads(handoff.read_text())
    check(doc['backupId'] == bid and doc['status'] == 'verified-staged-awaiting-promotion'
          and doc['snapshotEligible'] is False, 'explicit verified-staged non-eligible handoff')
    check((Path(doc['receivedDirectory']) / 'dataset-manifest.json').is_file(), 'received tree complete')
    check(cmd(*transfer).returncode != 0, 'duplicate ID refused; previous handoff unchanged')
    check(not list(incoming.glob('.diaries-incoming-*')) == [], 'success retains private receiver staging')
    check(cmd(REPLICATION, '_copy', '--receiver-root', incoming).returncode != 0, 'unpinned direct copy refused')
    # Intentionally bad validation executable: no handoff and no leftover partial tree.
    other = base / 'other'; other.mkdir()
    bad = cmd(REPLICATION, 'transfer', '--published-root', public, '--receiver-root', other,
              '--manifest-tool', base / 'missing-manifest-tool.py')
    check(bad.returncode != 0 and not list(other.iterdir()), 'failed verification has no handoff or partial receiver data')
print('PASS: 0034 Step 6 isolated replication suite')
