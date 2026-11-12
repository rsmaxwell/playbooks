#!/usr/bin/env python3
"""Disposable ext4-compatible publisher regression; no production services accessed."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROLE = Path(__file__).resolve().parents[1]
SCRIPTS = ROLE / 'files/sync/scripts'
PUBLISHER = SCRIPTS / 'complete-dataset-publisher.py'
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('verify-complete-dataset-manifest.py'))
# Importing that fixture executes tests, so extract only its fixture helpers.
source = Path(__file__).with_name('verify-complete-dataset-manifest.py').read_text()
fixture_source = source[:source.index('def mutate_manifest(')]
namespace = {'__name__': 'fixture_support', '__file__': str(Path(__file__).with_name('verify-complete-dataset-manifest.py'))}
exec(compile(fixture_source, namespace['__file__'], 'exec'), namespace)

def call(root, *args):
    return subprocess.run([sys.executable, str(PUBLISHER), '--published-root', str(root), *map(str,args)], capture_output=True, text=True)

def ok(test, name):
    assert test, name
    print('PASS:', name)

with tempfile.TemporaryDirectory(prefix='0034-step5-') as d:
    base = Path(d); published = base / 'diaries-backup'; inputs = base / 'inputs'; inputs.mkdir()
    first = namespace['create_candidate'](inputs)
    ok(namespace['write_manifest'](first).returncode == 0, 'synthetic schema-2 candidate constructed')
    first_id = first.name[1:-8]; first.rename(inputs / first_id); first = inputs / first_id
    ok(call(published, 'preflight').returncode == 0 and not published.exists(), 'preflight non-mutating')
    ok(call(published, 'create', first).returncode == 0, 'first generation published')
    ok(call(published, 'verify-current').returncode == 0 and call(published, 'show-current-id').stdout.strip() == first_id, 'current verified and identity visible')
    bad = inputs / '20261008-120000Z'
    import shutil
    shutil.copytree(first, bad)
    (bad / 'files/a.txt').write_text('corrupted\n')
    ok(call(published, 'create', bad).returncode != 0 and call(published, 'show-current-id').stdout.strip() == first_id, 'invalid second candidate cannot replace first')
    # Valid second fixture: copy candidate and build a fresh schema-2 manifest with second ID.
    second_id = '20261008-130000Z'
    # existing fixture uses the first ID: create in separate base to avoid existing tree
    fresh = base / 'fresh'; fresh.mkdir()
    second = namespace['create_candidate'](fresh)
    renamed = fresh / ('.' + second_id + '.partial'); second.rename(renamed)
    ns_write = namespace['write_manifest']
    # Helper's writer obtains ID from directory, requiring no custom override.
    ok(ns_write(renamed).returncode == 0, 'second schema-2 candidate constructed')
    second = fresh / second_id; renamed.rename(second)
    reader = subprocess.Popen([sys.executable, str(PUBLISHER), '--published-root', str(published), 'pin-run', '--', sys.executable, '-c', 'import os,time;print(os.environ["DIARIES_PINNED_BACKUP_ID"],flush=True);time.sleep(1.2)'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ok(reader.stdout.readline().strip() == first_id, 'reader pinned first generation under shared lock')
    writer = subprocess.Popen([sys.executable, str(PUBLISHER), '--published-root', str(published), 'create', str(second)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(.25)
    ok(writer.poll() is None and published.resolve().name == first_id, 'publication blocked by active reader')
    reader.wait(timeout=5); stdout, stderr = writer.communicate(timeout=5)
    ok(reader.returncode == 0 and writer.returncode == 0, 'reader exits then second generation publishes')
    ok(call(published, 'show-current-id').stdout.strip() == second_id and call(published, 'verify-current').returncode == 0, 'second generation verified at stable path')
    ok((published.parent / '.diaries-backup-generations' / first_id).exists(), 'previous generation retained for rollback')
    again = call(published, 'create', second)
    ok(again.returncode == 0 and f'ALREADY_PUBLISHED {second_id}' in again.stdout, 'identical current generation is idempotent')
    ok(call(published, 'show-current-id').stdout.strip() == second_id, 'no-op does not move stable pointer')
    # Rebuild the same backup ID with a different *valid* manifest: refuse the collision.
    conflicting = base / 'conflicting'; conflicting.mkdir()
    conflicting_candidate = conflicting / second_id
    shutil.copytree(second, conflicting_candidate)
    differing_manifest = conflicting_candidate / 'dataset-manifest.json'
    different = json.loads(differing_manifest.read_text())
    different['testConflictMetadata'] = 'different-identity'
    differing_manifest.write_text(json.dumps(different, sort_keys=True) + '\n')
    conflict = call(published, 'create', conflicting_candidate)
    ok(conflict.returncode != 0 and 'conflict' in conflict.stderr.lower(), 'same ID with different manifest rejected')
    ok(call(published, 'create', first).returncode != 0, 'historical generation cannot silently roll back current pointer')
    ok(not list(base.glob('.diaries-backup-link.*')) and not list((base / '.diaries-backup-generations').glob('*.partial')), 'temporary publication artefacts cleared')
print('PASS: 0034 Step 5 isolated publisher suite')

# 0036 opt-in publisher regression: unchanged Files share storage, DB/manifest do not.
with tempfile.TemporaryDirectory(prefix='0036-step3-linked-') as d:
    base = Path(d); root = base / 'diaries-backup'; inputs = base / 'inputs'; inputs.mkdir()
    candidate = namespace['create_candidate'](inputs)
    ok(namespace['write_manifest'](candidate).returncode == 0, 'linked synthetic manifest')
    source_id = candidate.name[1:-8]
    candidate.rename(inputs / source_id); candidate = inputs / source_id
    linked = call(root, 'create-linked', candidate)
    ok(linked.returncode == 0, 'linked publication succeeds: ' + linked.stderr)
    published = root.resolve()
    original_file = candidate / 'files/a.txt'
    linked_file = published / 'files/a.txt'
    ok(original_file.stat().st_ino == linked_file.stat().st_ino and original_file.stat().st_nlink >= 2,
       'Files inode reused without a second data copy')
    ok((candidate / 'database/diaries.dump').stat().st_ino != (published / 'database/diaries.dump').stat().st_ino,
       'DB dump has an independent inode')
    ok((candidate / 'dataset-manifest.json').stat().st_ino != (published / 'dataset-manifest.json').stat().st_ino,
       'manifest has an independent inode')
    ok(call(root, 'verify-current').returncode == 0, 'linked generation verifies')
    # A corrupt or unsupported file must not change published pointer.
    badroot = base / 'bad'; badroot.mkdir()
    bad = badroot / '20261015-130000Z'
    shutil.copytree(candidate, bad)
    (bad / 'files/a.txt').write_text('bad data')
    ok(call(root, 'create-linked', bad).returncode != 0 and root.resolve() == published,
       'invalid linked candidate cannot advance pointer')
    ok(call(root, 'create-linked', candidate).returncode == 0,
       'linked publication remains idempotent')
print('PASS: 0036 Step 3 opt-in linked publisher tests')
