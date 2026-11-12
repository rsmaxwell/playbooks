#!/usr/bin/env python3
"""0040-FEAT: simple native Btrfs agreed-parent replication (opt-in).

Single local flock per host, small agreed-parent record, ordinary logs,
receiver-owned inspection/cleanup, one attempt per scheduled cycle.
The source status command is read-only and never initiates a sender cycle.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time

STAMP = re.compile(r"[0-9]{8}-[0-9]{6}Z\Z")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
SOURCE = Path('/media/usb/@snapshots/@data')
RECEIVED = Path('/@data/mars-received/@data')
SOURCE_MOUNT = Path('/media/usb')
RECEIVER_MOUNT = Path('/')
SOURCE_FS = '72d1d8ea-900e-4fca-837f-1b1febec036c'
RECEIVER_FS = 'b915f967-7cb4-4c14-b11b-f52209637a22'
SOURCE_STATE = Path('/media/usb/@snapshots/.simple-agreed-parent.json')
RECEIVER_STATE = Path('/@data/mars-received/.replication-state/.simple-agreed-parent.json')
MANAGER_LOCK = Path('/run/lock/btrfs-snapshot-manager.lock')
REMOTE = 'richard@10.254.22.1'
SSH_PORT = '39263'
SSH_USER = 'richard'
INSTALL = '/usr/local/bin/btrfs-simplified-replication'
TIMEOUT = 6 * 60 * 60

class Refuse(RuntimeError):
    pass

class Deferred(Refuse):
    pass

def require(ok, reason):
    if not ok:
        raise Refuse(reason)

def timestamp(s):
    require(isinstance(s, str) and STAMP.fullmatch(s), 'Invalid timestamp')
    return s

def uid(s):
    require(isinstance(s, str) and UUID.fullmatch(s), 'Invalid UUID')
    return s

def record(stamp, uuid):
    return {'timestamp': timestamp(stamp), 'uuid': uid(uuid)}

def validate_state(data):
    require(type(data) is dict and set(data) == {'schema', 'parent', 'prior'} and
            type(data['schema']) is int and data['schema'] == 1, 'Invalid state schema')
    def item(obj):
        require(type(obj) is dict and set(obj) == {'timestamp', 'uuid'}, 'Invalid parent record')
        return record(obj['timestamp'], obj['uuid'])
    parent = item(data['parent'])
    prior = item(data['prior']) if data['prior'] is not None else None
    require(prior is None or prior['timestamp'] < parent['timestamp'], 'Invalid prior generation')
    return {'schema': 1, 'parent': parent, 'prior': prior}

def initial_state(stamp, uuid):
    return validate_state({'schema': 1, 'parent': record(stamp, uuid), 'prior': None})

def advance(state, stamp, uuid):
    before = validate_state(state)
    next_parent = record(stamp, uuid)
    require(next_parent['timestamp'] > before['parent']['timestamp'], 'Candidate not newer than parent')
    return validate_state({'schema': 1, 'parent': next_parent, 'prior': before['parent']})

def safe_directory(path):
    require(path.is_dir() and not path.is_symlink(), f'Unsafe directory: {path}')

def load_state(path):
    safe_directory(path.parent)
    require(not path.is_symlink() and path.is_file(), f'Missing/unsafe agreed parent: {path}')
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == 0 and
            not info.st_mode & 0o077 and info.st_size <= 4096, 'Unsafe state permissions/size')
    return validate_state(json.loads(path.read_text(encoding='utf-8')))

def save_state(path, state, *, create=False):
    validated = validate_state(state)
    safe_directory(path.parent)
    if create:
        require(not path.exists() and not path.is_symlink(), 'State already exists')
    else:
        load_state(path)
    fd, temp = tempfile.mkstemp(prefix='.simple-state-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(validated, out, sort_keys=True)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def take_lock(path=None, *, create=True):
    # Resolve the configured lock at call time, including in isolated fixtures.
    if path is None:
        path = MANAGER_LOCK
    require(not path.is_symlink(), 'Unsafe lock path')
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'Invalid lock file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Deferred('DEFERRED: local snapshot-manager lock busy') from exc
        return fd
    except BaseException:
        os.close(fd)
        raise

@contextmanager
def locked(*, create=True):
    fd = take_lock(create=create)
    try:
        yield
    finally:
        os.close(fd)

def call(*args, input=None, timeout=60):
    return subprocess.run(list(args), input=input, check=True, text=True,
                          capture_output=True, timeout=timeout)

def require_filesystem(mount, expected):
    # A mounted data volume must not silently be replaced by an ordinary directory.
    data = call('btrfs', 'filesystem', 'show', str(mount)).stdout
    require(re.search(r'\buuid:\s*' + re.escape(expected) + r'\b', data, re.I),
            f'Unexpected Btrfs filesystem at {mount}')

def subvolume_info(root, stamp):
    timestamp(stamp)
    safe_directory(root)
    path = root / stamp
    require(not path.is_symlink(), 'Candidate is symlink')
    if not path.exists():
        return None
    require(path.is_dir(), 'Candidate is not a directory')
    output = call('btrfs', 'subvolume', 'show', str(path)).stdout
    details = dict(re.findall(r'^\s*(UUID|Received UUID|Flags|Parent UUID):\s*(.*?)\s*$', output, re.M))
    require(set(details) == {'UUID', 'Received UUID', 'Flags', 'Parent UUID'} and
            UUID.fullmatch(details['UUID']), 'Candidate is not a verified Btrfs subvolume')
    return details

def verified(info, expected_uuid, *, received):
    return info is not None and info['Flags'] == 'readonly' and (
        info['Received UUID'] == expected_uuid if received else
        info['UUID'] == expected_uuid and info['Received UUID'] == '-')

def protected_stamps(state):
    value = validate_state(state)
    return {item['timestamp'] for item in (value['parent'], value['prior']) if item}

def legacy_blocks():
    state = RECEIVER_STATE.parent
    # A dormant older recovery transaction must be reconciled before changing the
    # receiver dataset. Only these fixed legacy names are considered.
    return any((state / name).exists() or (state / name).is_symlink() for name in (
        '.agreed-parent-transfer-pending.json', '.receiver-prune-pending.json',
        '.agreed-parent-provisional.json'))

def classify_candidate(stamp, uuid, state, *, inspect, receipts_dir=RECEIVER_STATE.parent):
    timestamp(stamp); uid(uuid)
    require(stamp not in protected_stamps(state), 'Candidate protected by agreed-parent state')
    require(not legacy_blocks(), 'Legacy transaction pending')
    # Independent historical holds are never deletion candidates.
    holds = Path('/etc/btrfs-receiver-checkpoint-holds.json')
    if holds.exists():
        require(not holds.is_symlink(), 'Unsafe checkpoint holds')
        content = json.loads(holds.read_text())
        # Check all nested dictionaries because inventory layout varies by generation.
        require(stamp not in json.dumps(content), 'Candidate appears in independent holds')
    require(not (receipts_dir / (stamp + '.json')).exists() and
            not (receipts_dir / (stamp + '.json')).is_symlink(), 'Candidate has legacy receipt')
    info = inspect(stamp)
    if info is None:
        return 'absent'
    if verified(info, uuid, received=True):
        return 'complete'
    # Never delete a readonly candidate, a received UUID, or an unexpected object.
    require(info['Flags'] != 'readonly' and info['Received UUID'] == '-' and
            UUID.fullmatch(info['UUID']), 'Ambiguous candidate; manual review')
    return 'incomplete'

def remove_incomplete(stamp, uuid, state, *, inspect, delete, readback):
    require(classify_candidate(stamp, uuid, state, inspect=inspect) == 'incomplete',
            'Cleanup not authorised')
    before = inspect(stamp)
    # Recheck immediately before the only destructive operation.
    require(classify_candidate(stamp, uuid, state, inspect=inspect) == 'incomplete' and
            inspect(stamp)['UUID'] == before['UUID'], 'Candidate changed before cleanup')
    delete(stamp)
    require(readback(stamp) is None, 'Deleted candidate still present')
    return True

def ssh_command(*args):
    require(all(isinstance(x, str) and '\x00' not in x for x in args), 'Unsafe SSH argument')
    command = shlex.join(['sudo', '-n', INSTALL, 'receiver', *args])
    return ['sudo', '-n', '-u', SSH_USER, 'ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
            '-p', SSH_PORT, REMOTE, command]

def peer(*args):
    result = subprocess.run(ssh_command(*args), capture_output=True,
                            text=True, timeout=90)
    if result.returncode == 75:
        raise Deferred('DEFERRED: receiver snapshot-manager lock busy')
    require(result.returncode == 0, 'Receiver failed: ' + result.stderr[-2000:])
    return json.loads(result.stdout)

def choose_next(current, *, source_root=SOURCE, inspect=None):
    inspect = inspect or (lambda name: subvolume_info(source_root, name))
    safe_directory(source_root)
    # Match the established daily --latest policy: one incremental transfer to
    # the newest eligible snapshot, rather than falling behind hourly creation.
    items = sorted((entry.name for entry in source_root.iterdir()
                    if not entry.is_symlink() and entry.is_dir() and STAMP.fullmatch(entry.name)
                    and entry.name > current), reverse=True)
    for stamp in items:
        info = inspect(stamp)
        require(info is not None and info['Flags'] == 'readonly' and
                info['Received UUID'] == '-' and UUID.fullmatch(info['UUID']),
                'Unsafe source candidate: ' + stamp)
        return stamp, info['UUID']
    return None

def reconcile(source, remote):
    a, b = validate_state(source), validate_state(remote)
    if a == b:
        return 'equal'
    if b['prior'] == a['parent'] and b['parent']['timestamp'] > a['parent']['timestamp']:
        return 'receiver-ahead'
    raise Refuse('Agreed-parent states differ ambiguously; preserve both and investigate')

def receive_receiver(stamp, uuid, old_stamp, old_uuid, *, run=call):
    safe_directory(RECEIVED)
    state = load_state(RECEIVER_STATE)
    require(state['parent'] == record(old_stamp, old_uuid), 'Receiver agreed parent changed')
    require(verified(subvolume_info(RECEIVED, old_stamp), old_uuid, received=True),
            'Receiver parent identity changed')
    classification = classify_candidate(stamp, uuid, state,
        inspect=lambda s: subvolume_info(RECEIVED, s))
    if classification == 'incomplete':
        # Not a general garbage collector: only the exact candidate is eligible.
        remove_incomplete(stamp, uuid, state,
            inspect=lambda s: subvolume_info(RECEIVED, s),
            delete=lambda s: run('btrfs', 'subvolume', 'delete', str(RECEIVED / s), timeout=90),
            readback=lambda s: subvolume_info(RECEIVED, s))
        print('INFO: cleaned one incomplete candidate; retrying receive', file=sys.stderr)
    elif classification == 'complete':
        raise Refuse('Candidate complete; use receiver advance without retransmission')
    run('btrfs', 'receive', str(RECEIVED), timeout=TIMEOUT)
    require(verified(subvolume_info(RECEIVED, stamp), uuid, received=True),
            'Received candidate identity/read-only mismatch')
    save_state(RECEIVER_STATE, advance(state, stamp, uuid))
    return {'status': 'received', 'state': load_state(RECEIVER_STATE)}

def receiver_main(args):
    with locked(create=(args.operation != 'status')):
        require_filesystem(RECEIVER_MOUNT, RECEIVER_FS)
        safe_directory(RECEIVED)
        if args.operation == 'status':
            state = load_state(RECEIVER_STATE)
            result = {'state': state}
            if args.snapshot:
                result['candidate'] = subvolume_info(RECEIVED, args.snapshot)
        elif args.operation == 'bootstrap':
            require(args.snapshot and args.uuid, 'Missing bootstrap parent')
            require(verified(subvolume_info(RECEIVED, args.snapshot), args.uuid, received=True),
                    'Invalid receiver bootstrap identity')
            wanted = initial_state(args.snapshot, args.uuid)
            if RECEIVER_STATE.exists():
                require(load_state(RECEIVER_STATE) == wanted, 'Receiver already bootstrapped differently')
            else:
                save_state(RECEIVER_STATE, wanted, create=True)
            result = {'state': load_state(RECEIVER_STATE)}
        elif args.operation in ('receive', 'advance'):
            require(all((args.snapshot, args.uuid, args.parent, args.parent_uuid)),
                    'Missing candidate/parent')
            state = load_state(RECEIVER_STATE)
            require(state['parent'] == record(args.parent, args.parent_uuid),
                    'Receiver parent state changed')
            require(verified(subvolume_info(RECEIVED, args.parent), args.parent_uuid, received=True),
                    'Receiver parent identity invalid')
            if args.operation == 'advance':
                require(classify_candidate(args.snapshot, args.uuid, state,
                    inspect=lambda s: subvolume_info(RECEIVED, s)) == 'complete',
                    'Candidate not already complete')
                save_state(RECEIVER_STATE, advance(state, args.snapshot, args.uuid))
                result = {'state': load_state(RECEIVER_STATE), 'status': 'reconciled'}
            else:
                # Run btrfs receive with caller's stdin; do not buffer the binary stream.
                result = receive_receiver(args.snapshot, args.uuid, args.parent,
                                          args.parent_uuid, run=run_receive_command)
        else:
            raise Refuse('Unsupported receiver operation')
        print(json.dumps(result, sort_keys=True), flush=True)

def run_receive_command(*argv, timeout):
    with subprocess.Popen(list(argv), stdin=sys.stdin.buffer if argv[1] == 'receive' else None,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE) as child:
        try:
            _, errors = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            child.kill(); child.communicate()
            raise Refuse('Btrfs operation timed out')
        require(child.returncode == 0, 'Btrfs operation failed: ' + errors.decode(errors='replace')[-2000:])

def stream_send(parent, candidate):
    command = ['btrfs', 'send', '-p', str(SOURCE / parent), str(SOURCE / candidate)]
    remote_command = ssh_command('receive', '--snapshot', candidate,
                                 '--uuid', subvolume_info(SOURCE, candidate)['UUID'],
                                 '--parent', parent,
                                 '--parent-uuid', subvolume_info(SOURCE, parent)['UUID'])
    # Disk-backed stderr prevents large sender diagnostics filling a pipe
    # while the receiver is blocked waiting for the next stream bytes.
    with tempfile.TemporaryFile() as send_errors, subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=send_errors,
            start_new_session=True) as sender:
        with subprocess.Popen(remote_command, stdin=sender.stdout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              start_new_session=True) as receiver:
            sender.stdout.close()
            try:
                output, remote_error = receiver.communicate(timeout=TIMEOUT)
                sender.wait(timeout=15)
                send_errors.seek(0)
                sender_error = send_errors.read()[-2000:]
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                receiver.kill(); sender.kill()
                receiver.communicate(); sender.communicate()
                raise Refuse('Transfer timeout/interruption; parent unchanged locally')
            if receiver.returncode == 75:
                raise Deferred('DEFERRED: receiver lock busy during transfer')
            require(sender.returncode == 0 and receiver.returncode == 0,
                    'Transfer failed: sender=' + str(sender.returncode) +
                    ' receiver=' + str(receiver.returncode) + ' ' +
                    (sender_error + remote_error).decode(errors='replace')[-2000:])
            return json.loads(output)

def sender_readonly_status():
    """Inspect both ends without sending, advancing or saving agreed-parent state.

    Uses the same root-owned manager lock as the scheduled sender.  Refusal or
    a busy receiver is reported as an unavailable preflight, never a transfer.
    """
    source = load_state(SOURCE_STATE)
    parent = source['parent']
    parent_info = subvolume_info(SOURCE, parent['timestamp'])
    require(verified(parent_info, parent['uuid'], received=False),
            'Source parent identity invalid')
    if source['prior']:
        prior = source['prior']
        require(verified(subvolume_info(SOURCE, prior['timestamp']),
                         prior['uuid'], received=False), 'Source prior identity invalid')

    remote = validate_state(peer('status')['state'])
    relation = reconcile(source, remote)
    # Verify the actual Btrfs Received UUID, not only the remote JSON record.
    receiver_parent = remote['parent']
    inspection = peer('status', '--snapshot', receiver_parent['timestamp'])
    require(validate_state(inspection['state']) == remote and
            verified(inspection['candidate'], receiver_parent['uuid'], received=True),
            'Receiver parent identity or agreed-parent state changed')

    if relation == 'receiver-ahead':
        require(verified(subvolume_info(SOURCE, receiver_parent['timestamp']),
                         receiver_parent['uuid'], received=False),
                'Receiver ahead but source new parent is invalid')
        preflight = {'action': 'receiver-ahead-reconciliation-required',
                     'source': None, 'parent': parent['timestamp']}
    else:
        selected = choose_next(parent['timestamp'])
        if selected:
            stamp, uuid = selected
            candidate = subvolume_info(SOURCE, stamp)
            require(candidate['Parent UUID'] == parent_info['Parent UUID'],
                    'Candidate source lineage differs from agreed parent')
            preflight = {'action': 'incremental', 'source': stamp,
                         'source_uuid': uuid, 'parent': parent['timestamp']}
        else:
            preflight = {'action': 'up-to-date', 'source': None,
                         'parent': parent['timestamp']}
    return {'state': source, 'receiver': remote, 'relation': relation,
            'receiver_parent_verified': True, 'preflight': preflight}

def sender_main(args):
    with locked(create=(args.operation != 'status')):
        require_filesystem(SOURCE_MOUNT, SOURCE_FS)
        safe_directory(SOURCE)
        if args.operation == 'bootstrap':
            require(args.snapshot, 'Missing initial snapshot')
            source = subvolume_info(SOURCE, args.snapshot)
            require(source and source['Flags'] == 'readonly' and
                    source['Received UUID'] == '-', 'Invalid local bootstrap')
            expected = initial_state(args.snapshot, source['UUID'])
            if SOURCE_STATE.exists():
                require(load_state(SOURCE_STATE) == expected, 'Source already bootstrapped differently')
            result = peer('bootstrap', '--snapshot', args.snapshot, '--uuid', source['UUID'])
            require(result['state'] == expected, 'Receiver initialisation mismatch')
            if not SOURCE_STATE.exists():
                save_state(SOURCE_STATE, expected, create=True)
            print('SUCCESS: both agreed-parent records initialised')
            return
        if args.operation == 'status':
            print(json.dumps(sender_readonly_status(), sort_keys=True))
            return
        current = load_state(SOURCE_STATE)
        require(verified(subvolume_info(SOURCE, current['parent']['timestamp']),
                         current['parent']['uuid'], received=False), 'Source parent invalid')
        remote_state = peer('status')['state']
        relation = reconcile(current, remote_state)
        if relation == 'receiver-ahead':
            new = remote_state['parent']
            require(verified(subvolume_info(SOURCE, new['timestamp']), new['uuid'], received=False),
                    'Cannot reconcile source: new parent missing/mismatched')
            save_state(SOURCE_STATE, remote_state)
            print('SUCCESS: reconciled receiver-ahead transfer without retransmission')
            return
        next_snapshot = choose_next(current['parent']['timestamp'])
        if next_snapshot is None:
            print('SUCCESS: no newer eligible source snapshot')
            return
        stamp, uuid = next_snapshot
        candidate_info = subvolume_info(SOURCE, stamp)
        parent_info = subvolume_info(SOURCE, current['parent']['timestamp'])
        require(candidate_info['Parent UUID'] == parent_info['Parent UUID'],
                'Candidate source lineage differs from agreed parent')
        status = peer('status', '--snapshot', stamp)
        require(status['state'] == current, 'Receiver state changed')
        prior = current['parent']
        if verified(status['candidate'], uuid, received=True):
            response = peer('advance', '--snapshot', stamp, '--uuid', uuid,
                            '--parent', prior['timestamp'], '--parent-uuid', prior['uuid'])
        else:
            # The receiver owns exact candidate cleanup and at most one receive attempt.
            response = stream_send(prior['timestamp'], stamp)
        expected = advance(current, stamp, uuid)
        require(response['state'] == expected, 'Receiver did not confirm agreed-parent advancement')
        check = peer('status', '--snapshot', stamp)
        require(check['state'] == expected and
                verified(check['candidate'], uuid, received=True), 'Receiver readback mismatch')
        save_state(SOURCE_STATE, expected)
        print('SUCCESS: common parent advanced to ' + stamp)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', choices=['sender','receiver'])
    parser.add_argument('operation', choices=['cycle','status','bootstrap','receive','advance'])
    parser.add_argument('--snapshot')
    parser.add_argument('--uuid')
    parser.add_argument('--parent')
    parser.add_argument('--parent-uuid')
    args = parser.parse_args(argv)
    try:
        require(os.geteuid() == 0, 'Must run as root')
        if args.snapshot:
            timestamp(args.snapshot)
        if args.uuid:
            uid(args.uuid)
        if args.parent:
            timestamp(args.parent)
        if args.parent_uuid:
            uid(args.parent_uuid)
        if args.host == 'sender':
            require(args.operation in ('cycle','bootstrap','status'), 'Unsupported sender operation')
            sender_main(args)
        else:
            require(args.operation in ('status','bootstrap','receive','advance'),
                    'Unsupported receiver operation')
            receiver_main(args)
        return 0
    except Deferred as e:
        print(str(e), file=sys.stderr)
        return 75
    except (Refuse, OSError, ValueError, subprocess.SubprocessError, KeyError, json.JSONDecodeError) as e:
        print('FAILED: ' + str(e), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
