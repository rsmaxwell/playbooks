#!/usr/bin/env python3
"""0034 Step 6: opt-in pinned generation transfer to a private receiver staging tree.

This command does not modify the receiving live mirror or create Btrfs snapshots.
Only a validated JSON handoff is eligible for a subsequent explicitly controlled promotion.
Source and receiver paths must be explicitly provided by the operator.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def fail(message):
    raise RuntimeError(message)


def verify(path, manifest_tool):
    manifest = path / 'dataset-manifest.json'
    if not manifest.is_file() or manifest.is_symlink():
        fail('receiver manifest missing or symlink')
    doc = json.loads(manifest.read_text())
    subprocess.run([sys.executable, str(manifest_tool), 'verify', '--backup-dir', str(path)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if not isinstance(doc.get('backupId'), str) or not isinstance(doc.get('logicalDataset'), str):
        fail('manifest backup identity is incomplete')
    return doc


def transfer(args):
    receiver = args.receiver_root.absolute()
    if receiver.is_symlink() or not receiver.is_dir():
        fail('receiver root must exist and must not be symlink')
    # Restrict scratch operations to the provided private receiver parent.
    if args.published_root.absolute() == receiver or receiver in args.published_root.absolute().parents:
        fail('source and receiver overlap')
    publisher = Path(__file__).with_name('complete-dataset-publisher.py')
    cmd = [sys.executable, str(publisher), '--published-root', str(args.published_root),
           'pin-run', '--', sys.executable, str(Path(__file__)), '_copy',
           '--receiver-root', str(receiver), '--manifest-tool', str(args.manifest_tool)]
    return subprocess.call(cmd)


def copy_pinned(args):
    pinned = os.environ.get('DIARIES_PINNED_GENERATION', '')
    identity = os.environ.get('DIARIES_PINNED_BACKUP_ID', '')
    if not pinned or not identity:
        fail('copy requires publisher pin-run context')
    source = Path(pinned).resolve(strict=True)
    receiver = args.receiver_root.absolute()
    if not receiver.is_dir() or receiver.is_symlink():
        fail('receiver root unavailable')
    source_doc = verify(source, args.manifest_tool)
    if source_doc['backupId'] != identity:
        fail('pinned identity mismatch')
    stage_parent = receiver / ('.diaries-incoming-' + uuid.uuid4().hex)
    stage = stage_parent / identity
    handoff = receiver / ('diaries-handoff-' + identity + '.json')
    if handoff.exists() or handoff.is_symlink():
        fail('duplicate backup ID handoff; refusing overwrite')
    try:
        stage_parent.mkdir(mode=0o700)
        stage.mkdir(mode=0o700)
        # Never --inplace/--append. Deletion applies only within our new private stage.
        cmd = ['rsync', '-a', '--delete', '--', str(source) + '/', str(stage) + '/']
        subprocess.run(cmd, check=True)
        received_doc = verify(stage, args.manifest_tool)
        if received_doc['backupId'] != identity or received_doc['logicalDataset'] != source_doc['logicalDataset']:
            fail('received identity mismatch')
        # Stage is private, and verified before handoff; no snapshot-eligibility on failure.
        result = {'backupId': identity, 'logicalDataset': source_doc['logicalDataset'],
                  'sourceGeneration': str(source), 'receivedDirectory': str(stage),
                  'validation': 'schema-2-verified', 'snapshotEligible': False,
                  'status': 'verified-staged-awaiting-promotion'}
        temp = receiver / ('.handoff-' + uuid.uuid4().hex + '.json')
        try:
            with open(temp, 'x', encoding='utf-8') as stream:
                json.dump(result, stream, sort_keys=True, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, handoff)
        finally:
            temp.unlink(missing_ok=True)
        print(f'RECEIVED-VERIFIED {identity} {stage}')
        return 0
    except BaseException:
        # Never leave a false-success handoff. Preserve no partial incoming data.
        if stage_parent.exists():
            shutil.rmtree(stage_parent)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    x = sub.add_parser('transfer')
    x.add_argument('--published-root', type=Path, required=True)
    for command in (x, sub.add_parser('_copy', help=argparse.SUPPRESS)):
        command.add_argument('--receiver-root', type=Path, required=True)
        command.add_argument('--manifest-tool', type=Path, default=Path(__file__).with_name('complete-dataset-manifest.py'))
    a = parser.parse_args()
    return transfer(a) if a.action == 'transfer' else copy_pinned(a)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as e:
        print('ERROR:', e, file=sys.stderr)
        sys.exit(1)
