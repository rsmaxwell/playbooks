#!/usr/bin/env python3
"""Service-key forced SSH dispatcher; never evaluates SSH_ORIGINAL_COMMAND."""
import json
import os
import re
import shlex
import subprocess
import sys

GATE = '/usr/local/libexec/btrfs-replication-receiver-gate-0041'
STAMP = re.compile(r'[0-9]{8}-[0-9]{6}Z\Z')
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z')

class Reject(ValueError):
    pass

def parse_ssh_command(raw):
    if not isinstance(raw, str) or not raw or len(raw) > 400 or any(
            ord(ch) < 32 or ord(ch) > 126 for ch in raw):
        raise Reject('Missing or invalid SSH command')
    try:
        parts = shlex.split(raw, posix=True)
    except ValueError as exc:
        raise Reject('Invalid SSH quoting') from exc
    if len(parts) < 3 or parts[:2] != ['btrfs-replication', 'receiver']:
        raise Reject('Unauthorized command')
    op = parts[2]
    if op == 'status':
        if parts[3:] == []:
            return {'op': 'status', 'snapshot': None}
        if (len(parts) == 5 and parts[3] == '--snapshot' and
                STAMP.fullmatch(parts[4])):
            return {'op': 'status', 'snapshot': parts[4]}
        raise Reject('Invalid status arguments')
    if op not in ('receive', 'advance') or len(parts) != 11:
        raise Reject('Unauthorized operation')
    fields = ('snapshot', 'uuid', 'parent', 'parent_uuid')
    expressions = (STAMP, UUID, STAMP, UUID)
    request = {'op': op}
    for i, (field, pattern) in enumerate(zip(fields, expressions)):
        ix = 3 + 2 * i
        if parts[ix] != '--' + field.replace('_', '-') or not pattern.fullmatch(parts[ix + 1]):
            raise Reject('Invalid ' + field)
        request[field] = parts[ix + 1]
    if request['snapshot'] <= request['parent']:
        raise Reject('Candidate is not newer than parent')
    return request

def main():
    if len(sys.argv) != 1:
        raise Reject('No dispatcher arguments allowed')
    request = parse_ssh_command(os.environ.get('SSH_ORIGINAL_COMMAND'))
    header = json.dumps(request, separators=(',', ':'), sort_keys=True).encode('ascii') + b'\n'
    # Root sudoers admits ONLY the fixed no-argument gate. The gate independently
    # validates the header; neither side invokes a shell or uses eval.
    with subprocess.Popen(['sudo', '-n', GATE], stdin=subprocess.PIPE) as child:
        try:
            child.stdin.write(header)
            child.stdin.flush()
            if request['op'] == 'receive':
                while True:
                    chunk = os.read(0, 1024 * 1024)
                    if not chunk:
                        break
                    child.stdin.write(chunk)
            child.stdin.close()
        except BrokenPipeError:
            # Child already refused; propagate its exit status.
            try:
                child.stdin.close()
            except BrokenPipeError:
                pass
        return child.wait()

if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Reject, OSError) as exc:
        print('REFUSED: ' + str(exc), file=sys.stderr)
        sys.exit(64)
