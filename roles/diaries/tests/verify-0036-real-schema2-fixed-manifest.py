#!/usr/bin/env python3
"""0036 Step 3 Gate 2: real schema-2 writer/validator on a disposable fixed root.

No production database, mounts or backup directories are accessed.
Database payloads are synthetic; the actual manifest CLI is invoked.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROLE = Path(__file__).resolve().parents[1]
TOOL = ROLE / 'files/sync/scripts/complete-dataset-manifest.py'
FIXTURE = Path(__file__).with_name('verify-complete-dataset-manifest.py')
BACKUP_ID = '20261015-193000Z'

def invoke(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)

def check(condition: bool, label: str, detail: str = '') -> None:
    if not condition:
        raise AssertionError(f'{label}: {detail}')
    print(f'PASS: {label}')

def main() -> int:
    if not TOOL.is_file() or not FIXTURE.is_file():
        print('FAIL: authoritative schema-2 tool or existing fixture unavailable', file=sys.stderr)
        return 1
    spec = importlib.util.spec_from_file_location('schema2_test_fixture', FIXTURE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='diaries-0036-schema2-') as td:
        parent = Path(td)
        root = parent / 'diaries-backup'
        sample = module.create_candidate(parent)
        sample.rename(root)
        # Only the real manifest writer builds the manifest. The existing 0034
        # fixture builds the inventory and hash lists, avoiding duplicate formats.
        write = invoke('write', '--backup-dir', str(root), '--fixed-backup-id', BACKUP_ID,
            '--logical-dataset', 'common', '--launch-mode', 'production',
            '--known-consumer', 'production', '--database-storage-identity', 'disposable-db',
            '--database-name', 'diaries0036test', '--files-selector', 'disposable-files',
            '--files-root', '/disposable/nas',
            '--application-identity-json', '{"rehearsal":"0036-gate2"}',
            '--writer-method', 'disposable-rehearsal', '--writer', 'diaries-responder',
            '--writer-evidence', 'synthetic and quiesced', '--image-row-count', '2',
            '--catalogued-file-count', '2', '--staging-disposition', 'empty',
            '--staging-entry-count', '0', '--staging-note', 'not included',
            '--started-at', '2026-10-15T19:29:00+00:00',
            '--completed-at', '2026-10-15T19:30:00+00:00')
        check(write.returncode == 0, 'real schema-2 writer accepts a fixed directory', write.stderr)
        manifest = root / 'dataset-manifest.json'
        doc = json.loads(manifest.read_text())
        check(doc['schemaVersion'] == 2 and doc['backupId'] == BACKUP_ID and doc['status'] == 'complete',
              'writer preserves the schema-2 format and explicit backup ID')
        verify = invoke('verify', '--backup-dir', str(root), '--allow-fixed-working-root')
        check(verify.returncode == 0, 'real validator verifies all fixed-dataset components', verify.stderr)
        legacy = invoke('verify', '--backup-dir', str(root))
        check(legacy.returncode != 0, 'fixed-root validation requires explicit opt-in')

        marker = parent / '.diaries-backup-fixed-verified.json'
        def accept_if_verified() -> subprocess.CompletedProcess[str]:
            marker.unlink(missing_ok=True)
            result = invoke('verify', '--backup-dir', str(root), '--allow-fixed-working-root')
            if result.returncode == 0:
                data = manifest.read_bytes()
                marker.write_text(json.dumps({
                    'schemaVersion': 1, 'backupId': doc['backupId'],
                    'manifestSha256': hashlib.sha256(data).hexdigest(), 'root': str(root)
                }) + '\n')
            return result
        check(accept_if_verified().returncode == 0 and marker.exists(),
              'valid dataset receives acceptance marker after verification')
        files = root / 'files/a.txt'
        original = files.read_bytes()
        files.write_bytes(original + b'corruption')
        failed = accept_if_verified()
        check(failed.returncode != 0 and not marker.exists(),
              'Files corruption rejected and acceptance marker invalidated', failed.stderr)
        files.write_bytes(original)
        check(accept_if_verified().returncode == 0 and marker.exists(),
              'Files recovery re-verifies and re-establishes marker')
        dump = root / 'database/diaries.dump'
        original_dump = dump.read_bytes()
        dump.write_bytes(original_dump + b'corruption')
        failed = accept_if_verified()
        check(failed.returncode != 0 and not marker.exists(),
              'database dump corruption rejected and marker invalidated', failed.stderr)
        dump.write_bytes(original_dump)
        check(accept_if_verified().returncode == 0 and marker.exists(),
              'database restoration re-verifies and re-establishes marker')
        # The real writer should reject a root with a different name.
        wrong = parent / 'wrong-root'
        shutil.copytree(root, wrong)
        bad_write = invoke('write', '--backup-dir', str(wrong), '--fixed-backup-id', BACKUP_ID,
                           '--logical-dataset', 'common')
        check(bad_write.returncode != 0, 'fixed manifest writer refuses wrong root')
    print('PASS: 0036 Step 3 Gate 2 real schema-2 fixed-root manifest rehearsal')
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        raise SystemExit(1)
