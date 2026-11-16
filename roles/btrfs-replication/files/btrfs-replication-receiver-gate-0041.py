#!/usr/bin/env python3
"""Root-owned fixed sudo gate: unbuffered request header followed by raw stream.

This program is intentionally only a bounded authority filter. It does not
accept CLI options, shell commands, arbitrary filesystem paths or bootstrap.
The original Btrfs runtime retains the identity/hold/lock/recovery checks.
"""
import json
import os
import re
import signal
import sys

RUNTIME = '/usr/local/bin/btrfs-replication'
STAMP = re.compile(r'[0-9]{8}-[0-9]{6}Z\Z')
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')
MAX_HEADER = 512

class Reject(ValueError):
    pass

def read_header(fd):
    # DO NOT use buffered stdin.readline here: it can prefetch binary btrfs
    # stream bytes before execv, silently corrupting the transfer.
    data = bytearray()
    for _ in range(MAX_HEADER):
        ch = os.read(fd, 1)
        if ch == b'\n':
            return bytes(data)
        if not ch:
            raise Reject('Missing request newline')
        data.extend(ch)
    raise Reject('Request too long')

def parse_request(raw):
    def no_duplicates(pairs):
        out = {}
        for key, val in pairs:
            if key in out:
                raise Reject('Duplicate request field')
            out[key] = val
        return out
    try:
        obj = json.loads(raw.decode('ascii'), object_pairs_hook=no_duplicates)
    except (ValueError, UnicodeError) as exc:
        raise Reject('Invalid request encoding') from exc
    if type(obj) is not dict or obj.get('op') not in ('status', 'receive', 'advance'):
        raise Reject('Operation refused')
    op = obj['op']
    expected = {'op', 'snapshot'} if op == 'status' else {
        'op', 'snapshot', 'uuid', 'parent', 'parent_uuid'}
    if set(obj) != expected:
        raise Reject('Unexpected request fields')
    snap = obj['snapshot']
    if op == 'status':
        if snap is not None and (type(snap) is not str or not STAMP.fullmatch(snap)):
            raise Reject('Invalid status snapshot')
        return ['receiver', 'status'] + (['--snapshot', snap] if snap is not None else [])
    for key, pattern in (('snapshot', STAMP), ('uuid', UUID),
                         ('parent', STAMP), ('parent_uuid', UUID)):
        value = obj[key]
        if type(value) is not str or not pattern.fullmatch(value):
            raise Reject('Invalid ' + key)
    if obj['snapshot'] <= obj['parent']:
        raise Reject('Candidate must be newer than parent')
    return ['receiver', op, '--snapshot', obj['snapshot'], '--uuid', obj['uuid'],
            '--parent', obj['parent'], '--parent-uuid', obj['parent_uuid']]

def main():
    if os.geteuid() != 0 or len(sys.argv) != 1:
        raise Reject('Requires root and no CLI arguments')
    # An authenticated client may be malicious or interrupted before the
    # request header is complete. Do not keep a root gate blocked forever.
    signal.alarm(20)
    try:
        args = parse_request(read_header(0))
    finally:
        signal.alarm(0)
    # Keep stdin fd 0 at the exact byte after the newline, allowing the
    # existing receiver runtime to attach it directly to `btrfs receive`.
    os.execv(RUNTIME, [RUNTIME, *args])

if __name__ == '__main__':
    try:
        main()
    except (Reject, OSError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        raise SystemExit(64)
