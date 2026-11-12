#!/usr/bin/env python3
"""0040 Step 11: fixed-inventory, fail-closed one-time root-snapshot retirement.

Preview never deletes. Commit requires explicit authorisation, runtime-masked
replication service, and durable intent/completion receipts for each deletion. This is
historical change-control tooling, not a component of the snapshot manager.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/media/usb/@snapshots/root')
DATA = Path('/media/usb/@snapshots/@data')
CONFIG = Path('/etc/btrfs-snapshot-manager.json')
HOLDS = Path('/media/usb/@snapshots/.checkpoint-holds.json')
PROTECTION = Path('/media/usb/@snapshots/.replication-protection.json')
LOCK = Path('/run/lock/btrfs-snapshot-manager.lock')
MANIFEST = Path(__file__).with_name('root-retirement-manifest.json')
RECEIPT = Path('/media/usb/@snapshots/.0040-step11-root-retirement-receipt.jsonl')
AUTH = '0040-STEP11-DELETE-63-HISTORICAL-ROOT-SNAPSHOTS'
STAMP = re.compile(r'\d{8}-\d{6}Z\Z')
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')

class Refusal(Exception):
    pass

def run(*command):
    p = subprocess.run(command, capture_output=True, text=True)
    if p.returncode:
        raise Refusal(f"Command failed: {command}: {p.stderr.strip()}")
    return p.stdout

def metadata(path):
    output = run('btrfs', 'subvolume', 'show', str(path))
    values = {}
    for line in output.splitlines():
        if ':' in line:
            k, v = line.strip().split(':', 1)
            values[k] = v.strip()
    try:
        return int(values['Subvolume ID']), values['UUID'], values['Flags'].split()
    except (KeyError, ValueError) as e:
        raise Refusal(f'Invalid Btrfs identity: {path}: {e}') from e

def validate_manifest(manifest):
    if set(manifest) != {'schema', 'purpose', 'snapshots'} or manifest['schema'] != 1:
        raise Refusal('Invalid manifest schema')
    entries = manifest['snapshots']
    if len(entries) != 63:
        raise Refusal('Manifest must contain exactly 63 candidates')
    if [e['timestamp'] for e in entries] != sorted(e['timestamp'] for e in entries):
        raise Refusal('Manifest must be chronologically sorted')
    stamps = set()
    ids = set()
    uuids = set()
    for e in entries:
        if set(e) != {'timestamp', 'path', 'id', 'uuid'}:
            raise Refusal('Unexpected manifest fields')
        s = e['timestamp']
        if not isinstance(s, str) or not STAMP.fullmatch(s) or e['path'] != str(ROOT / s):
            raise Refusal('Unsafe manifest path')
        if not isinstance(e['id'], int) or isinstance(e['id'], bool) or e['id'] < 1:
            raise Refusal('Invalid subvolume ID')
        if not isinstance(e['uuid'], str) or not UUID.fullmatch(e['uuid']):
            raise Refusal('Invalid UUID')
        if s in stamps or e['id'] in ids or e['uuid'] in uuids:
            raise Refusal('Duplicate candidate identity')
        stamps.add(s); ids.add(e['id']); uuids.add(e['uuid'])
    return entries

def read_json(path):
    if path.is_symlink() or not path.is_file():
        raise Refusal(f'Absent/unsafe state: {path}')
    return json.loads(path.read_text())

def discover_root_candidates(lines):
    """Use filesystem-relative paths; ignore siblings but refuse nested roots."""
    prefix = '@snapshots/root/'
    observed = []
    for line in lines:
        if ' path ' not in line:
            raise Refusal(f'Unexpected Btrfs listing line: {line}')
        relative = line.split(' path ', 1)[1]
        if relative.startswith(prefix):
            remainder = relative[len(prefix):]
            if '/' in remainder:
                raise Refusal(f'Nested subvolume: {relative}')
            observed.append(remainder)
    return observed

def systemd_state(command, unit):
    result = subprocess.run(['systemctl', command, unit], capture_output=True, text=True)
    return result.stdout.strip(), result.returncode

def replication_inactive():
    state, code = systemd_state('is-active', 'btrfs-native-push.service')
    if state != 'inactive':
        raise Refusal(f'Replication service not inactive: {state} (code {code})')

def commit_replication_exclusion():
    # A runtime mask prohibits new service starts, including timer/manual activation.
    # It is applied outside this utility during the separately authorised cutover.
    # Never change systemd state here: a failed preflight must leave production alone.
    state, code = systemd_state('is-enabled', 'btrfs-native-push.service')
    if state not in ('masked', 'masked-runtime'):
        raise Refusal(f'Commit requires runtime-masked native push service; observed {state} ({code})')
    replication_inactive()

def durable_event(out, event, **fields):
    out.write(json.dumps({'event': event, **fields}, sort_keys=True) + '\n')
    out.flush()
    os.fsync(out.fileno())

def durable_receipt_dir():
    fd = os.open(str(RECEIPT.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def delete_with_receipt(entries, out):
    durable_event(out, 'BEGIN', count=len(entries),
                  manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())
    for e in entries:
        # Protection can change without the snapshot-manager lock (manual edits);
        # recheck the protected data and live source configuration each iteration.
        # Do NOT repeat full inventory preflight, as prior candidates were deleted.
        protection_preflight()
        commit_replication_exclusion()
        path = ROOT / e['timestamp']
        if path.is_symlink() or not path.is_dir():
            raise Refusal(f'Candidate absent/unsafe: {path}')
        sid, uuid, flags = metadata(path)
        if (sid, uuid) != (e['id'], e['uuid']) or 'readonly' not in flags:
            raise Refusal(f'Candidate changed: {path}')
        durable_event(out, 'DELETE_INTENT', **e)
        # Crash after this command but before DELETED will leave an ambiguous intent.
        # Never auto-retry; receipt presence blocks all subsequent commits.
        run('btrfs', 'subvolume', 'delete', str(path))
        durable_event(out, 'DELETED', **e)
        print('DELETED', e['timestamp'], flush=True)
    durable_event(out, 'COMPLETE', count=len(entries))

def protection_preflight():
    config = read_json(CONFIG)
    sources = config.get('sources')
    if not isinstance(sources, list) or len(sources) != 1 or sources[0].get('name') != '@data':
        raise Refusal('Manager is not @data-only')
    # Production schema stores flags on each source; it does not define
    # required_snapshot_sources or creation_source_names top-level keys.
    source = sources[0]
    if (source.get('path') != '/media/usb/@data'
            or any(type(source.get(flag)) is not bool or source[flag] is not True
                   for flag in ('required', 'creation', 'prune'))):
        raise Refusal('Unexpected @data source path/required/creation/prune flags')
    if ROOT.is_symlink() or not ROOT.is_dir() or DATA.is_symlink() or not DATA.is_dir():
        raise Refusal('Snapshot roots invalid')
    holds = read_json(HOLDS)
    required = {'20261013-171228Z', '20261018-165453Z'}
    if holds.get('schema') != 1 or not isinstance(holds.get('holds'), dict) or not required.issubset(holds['holds']):
        raise Refusal('Historical holds missing')
    if set(holds['holds']) != required:
        raise Refusal('Checkpoint hold set has changed; review first')
    for stamp in required:
        record = holds['holds'][stamp]
        if set(record.get('source_uuids', {})) != {'@data'}:
            raise Refusal(f'Non-@data checkpoint hold {stamp}')
        candidate = DATA / stamp
        if not candidate.is_dir() or candidate.is_symlink():
            raise Refusal(f'Checkpoint data missing {stamp}')
        _, uuid, flags = metadata(candidate)
        if uuid != record['source_uuids']['@data'] or 'readonly' not in flags:
            raise Refusal(f'Checkpoint UUID/flags mismatch {stamp}')
    pins = read_json(PROTECTION)
    if pins.get('schema') != 1 or not isinstance(pins.get('protected'), dict) or not pins['protected']:
        raise Refusal('Replication protection missing')
    for stamp, uuid in pins['protected'].items():
        if not STAMP.fullmatch(stamp) or not UUID.fullmatch(uuid):
            raise Refusal('Invalid replication pin')
        path = DATA / stamp
        if path.is_symlink() or not path.is_dir() or metadata(path)[1] != uuid:
            raise Refusal(f'Protected @data snapshot unavailable: {stamp}')
    # The source endpoint's hardcoded @data selection must still be deployed.
    endpoint = Path('/usr/local/libexec/btrfs-native-endpoint')
    if not endpoint.is_file() or "SOURCE_DIR = Path('/media/usb/@snapshots/@data')" not in endpoint.read_text():
        raise Refusal('Installed replication source endpoint has changed')
def base_preflight(entries):
    protection_preflight()
    replication_inactive()
    # Btrfs CLI listing must start at the mounted filesystem, not the nested
    # root snapshot directory. On mars, listing the latter can show zero root
    # candidates while listing /media/usb returns filesystem-relative paths.
    lines = run('btrfs', 'subvolume', 'list', '/media/usb').splitlines()
    observed = discover_root_candidates(lines)
    if sorted(observed) != sorted(e['timestamp'] for e in entries):
        raise Refusal(f'Btrfs root candidate mismatch ({len(observed)} vs {len(entries)})')
    actual = sorted(p.name for p in ROOT.iterdir())
    if actual != sorted(e['timestamp'] for e in entries):
        raise Refusal('Root directory contains unapproved entries')
    for e in entries:
        path = ROOT / e['timestamp']
        if path.is_symlink() or not path.is_dir():
            raise Refusal(f'Missing/unsafe candidate {path}')
        sid, uuid, flags = metadata(path)
        if (sid, uuid) != (e['id'], e['uuid']) or 'readonly' not in flags:
            raise Refusal(f'Identity/read-only mismatch: {path}')
    return True

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', action='store_true')
    parser.add_argument('--authorise', default='')
    args = parser.parse_args()
    if args.commit != bool(args.authorise):
        raise Refusal('Commit requires --authorise; preview must not supply it')
    if args.commit and args.authorise != AUTH:
        raise Refusal('Incorrect authorisation token')
    if os.geteuid() != 0:
        raise Refusal('Run as root')
    entries = validate_manifest(read_json(MANIFEST))
    # nonblocking flock shared with snapshot manager; protects competing create/prune.
    with LOCK.open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Refusal('Snapshot manager lock held; retry later') from exc
        if RECEIPT.exists():
            raise Refusal(f'Receipt already exists; no reruns supported: {RECEIPT}')
        base_preflight(entries)
        print(f'PASS: immutable manifest verified; {len(entries)} exact read-only root snapshots')
        for e in entries:
            print('CANDIDATE', e['timestamp'], e['id'], e['uuid'])
        if not args.commit:
            print('PREVIEW ONLY: no snapshots deleted')
            return
        commit_replication_exclusion()
        # Fail closed if receipt path already exists, create atomically and durably.
        fd = os.open(RECEIPT, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        # Persist the new directory entry before recording any deletion intent.
        try:
            durable_receipt_dir()
        except Exception:
            os.close(fd)
            raise
        with os.fdopen(fd, 'w', buffering=1) as out:
            delete_with_receipt(entries, out)
        print('COMMIT COMPLETE; retain receipt and manifest as evidence')

if __name__ == '__main__':
    try:
        main()
    except (Refusal, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        sys.exit(2)
