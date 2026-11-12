#!/usr/bin/env python3
"""0039-DEF: shared source/receiver Btrfs stale-qgroup housekeeping.

No mutation without --execute; no individual/bulk qgroup destroy, rescan,
subvolume changes, or replication-state changes. Use btrfs-progs native
clear-stale only, holding the canonical manager then writer locks.
"""
import argparse
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

MANAGER_LOCK = Path('/run/lock/btrfs-snapshot-manager.lock')
MAINTENANCE_CONFIG = Path('/etc/btrfs-stale-qgroups.json')
MANAGER_CONFIG = Path('/etc/btrfs-snapshot-manager.json')
QGROUP = re.compile(r'^(\d+)/(\d+)$')
# Accept only explicitly verified btrfs-progs output variants.
HEADERS = {
    ('qgroupid', 'referenced', 'exclusive', 'path'),  # v6.6.3 on both production hosts
    ('qgroupid', 'rfer', 'excl', 'path'),  # older/compact output
}


class Refused(RuntimeError):
    pass


def command(*argv, check=True):
    p = subprocess.run(list(argv), text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, check=False)
    if check and p.returncode:
        raise Refused(f'command failed rc={p.returncode}: {" ".join(argv)}: {p.stderr.strip()[:400]}')
    return p


def absolute_path(value, label):
    if not isinstance(value, str) or not value.startswith('/') or '\x00' in value:
        raise Refused(f'{label} must be an absolute path')
    path = Path(value)
    if '..' in path.parts or str(path) != value:
        raise Refused(f'{label} must be canonical')
    return path


def load_maintenance_config(path):
    """Load host-local configuration installed by Ansible, fail closed."""
    if path != MAINTENANCE_CONFIG:
        raise Refused('unexpected stale-qgroup maintenance configuration path')
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f'cannot read stale-qgroup maintenance configuration: {exc}') from exc
    if not isinstance(data, dict) or set(data) != {
            'schema', 'mode', 'filesystem', 'snapshot_manager_config',
            'expected_writer_lock', 'max_stale'}:
        raise Refused('invalid stale-qgroup configuration keys')
    if type(data['schema']) is not int or data['schema'] != 1:
        raise Refused('unsupported stale-qgroup configuration schema')
    if data['mode'] not in ('source', 'receiver'):
        raise Refused('invalid configured endpoint mode')
    if type(data['max_stale']) is not int or not 1 <= data['max_stale'] <= 2000:
        raise Refused('configured max-stale must be within 1..2000')
    manager = absolute_path(data['snapshot_manager_config'], 'snapshot-manager config')
    if manager != MANAGER_CONFIG:
        raise Refused('unexpected snapshot-manager configuration path')
    fs = absolute_path(data['filesystem'], 'filesystem')
    writer = absolute_path(data['expected_writer_lock'], 'expected writer lock')
    # Check independently of manager JSON so an accidentally swapped host
    # configuration never targets the other endpoint's filesystem.
    if (data['mode'], fs) not in (('source', Path('/media/usb')),
                                  ('receiver', Path('/'))):
        raise Refused('configured endpoint/filesystem mismatch')
    return dict(config_path=manager, fs=fs, mode=data['mode'],
                expected_writer=writer, max_stale=data['max_stale'])


def contract(config_path, fs, mode, expected_writer):
    if config_path != MANAGER_CONFIG:
        raise Refused('unexpected snapshot-manager configuration path')
    try:
        config = json.loads(config_path.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f'cannot read snapshot-manager configuration: {exc}') from exc
    if not isinstance(config, dict):
        raise Refused('invalid snapshot-manager configuration')
    if config.get('mode', 'source') != mode:
        raise Refused('snapshot-manager mode does not match endpoint')
    if absolute_path(config.get('lock_path'), 'manager lock') != MANAGER_LOCK:
        raise Refused('manager lock differs from canonical /run/lock path')
    writer = absolute_path(config.get('writer_lock_path'), 'writer lock')
    if writer != expected_writer or writer == MANAGER_LOCK:
        raise Refused('writer lock differs from expected endpoint lock')
    root = absolute_path(config.get('snapshot_root'), 'snapshot root')
    if mode == 'source':
        if fs != Path('/media/usb') or not root.is_relative_to(fs) or root == fs:
            raise Refused('source filesystem/snapshot root mismatch')
        if expected_writer != Path('/media/usb/@data/backup/.btrfs-snapshot-writer.lock'):
            raise Refused('unexpected source writer lock')
    elif mode == 'receiver':
        state = absolute_path(config.get('receiver_state_dir'), 'receiver state')
        if fs != Path('/') or root != Path('/@data/mars-received') or writer != state / 'writer.lock':
            raise Refused('receiver filesystem/state mismatch')
    else:
        raise Refused('unrecognised endpoint mode')
    return writer


def lock_file(path, *, create=False):
    # Every endpoint uses manager -> writer, matching agreed-parent operations.
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
            raise Refused(f'unsafe lock inode: {path}')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return os.fdopen(fd, 'r+')
    except BaseException:
        os.close(fd)
        raise


def verify_mount(fs):
    p = command('findmnt', '-n', '-o', 'TARGET,FSTYPE,UUID', '--mountpoint', str(fs))
    cols = p.stdout.strip().split()
    if len(cols) != 3 or cols[0] != str(fs) or cols[1] != 'btrfs' or not cols[2]:
        raise Refused(f'filesystem is not the expected mounted Btrfs filesystem: {fs}')
    return cols[2]


def parse_qgroups(output):
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines or tuple(field.lower() for field in lines[0].split()) not in HEADERS:
        raise Refused('unsupported qgroup show columns: require Qgroupid Referenced Exclusive Path (or known compact variant)')
    rows = {}
    for line in lines[1:]:
        if line.lstrip().startswith('----'):
            continue
        columns = line.split(None, 3)
        if len(columns) == 3 and QGROUP.fullmatch(columns[0]) and not columns[0].startswith('0/'):
            columns.append('')  # Unassigned higher-level qgroups have no path.
        if len(columns) != 4 or not QGROUP.fullmatch(columns[0]):
            raise Refused(f'unsupported qgroup show row: {line[:120]}')
        if columns[0] in rows:
            raise Refused(f'duplicate qgroup ID: {columns[0]}')
        if columns[3] == '<stale>' and not columns[0].startswith('0/'):
            raise Refused('non-level-0 qgroup marked stale')
        rows[columns[0]] = columns[3]
    return rows


def qgroups(fs):
    return parse_qgroups(command('btrfs', 'qgroup', 'show', str(fs)).stdout)


def subvolume_ids(fs):
    """Independently detect qgroups unmatched to live subvolume IDs.

    The native command decides which stale qgroups to clear. Unmarked orphan
    candidates (older progs) are only reported/refused, never destroyed.
    """
    output = command('btrfs', 'subvolume', 'list', str(fs)).stdout
    ids = set()
    for line in output.splitlines():
        match = re.match(r'^ID ([0-9]+)\s+', line.strip())
        if not match:
            raise Refused(f'unsupported subvolume list row: {line[:120]}')
        ids.add(int(match.group(1)))
    return ids


def pending_deletion_ids(fs):
    """Read the kernel's deferred-subvolume deletion queue (no waiting)."""
    output = command('btrfs', 'subvolume', 'list', '-d', str(fs)).stdout
    pending = set()
    for line in output.splitlines():
        # Observed btrfs-progs 6.6.3: ID 21336 gen 62204 top level 0 path DELETED
        match = re.fullmatch(r'ID (\d+) gen \d+ top level 0 path DELETED', line.strip())
        if not match:
            raise Refused(f'unsupported pending-subvolume row: {line[:120]}')
        sid = int(match.group(1))
        if sid in pending:
            raise Refused(f'duplicate pending deletion subvolume ID: {sid}')
        pending.add(sid)
    return pending


def expected_busy_errors(stderr, pending):
    """Only the observed EBUSY format for queued deletions is deferrable."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return False
    for line in lines:
        match = re.fullmatch(
            r'ERROR: cannot delete qgroup 0/(\d+): Device or resource busy', line)
        if not match or int(match.group(1)) not in pending:
            return False
    return True


def has_native_clear_stale():
    help_text = command('btrfs', 'qgroup', '--help', check=False)
    return re.search(r'\bclear-stale\b', help_text.stdout + help_text.stderr) is not None


def run(*, execute, config_path, fs, mode, expected_writer, max_stale=2000):
    if os.geteuid() != 0:
        raise Refused('must run as root')
    if max_stale < 1 or max_stale > 2000:
        raise Refused('max-stale must be within 1..2000')
    writer = contract(config_path, fs, mode, expected_writer)
    with ExitStack() as locks:
        locks.enter_context(lock_file(MANAGER_LOCK, create=True))
        locks.enter_context(lock_file(writer))
        uuid = verify_mount(fs)
        before = qgroups(fs)
        stale = sorted(k for k, v in before.items() if v == '<stale>')
        live_ids = subvolume_ids(fs)
        unexpected_live_stale = [k for k in stale if int(k.split('/')[1]) in live_ids]
        if unexpected_live_stale:
            raise Refused(f'stale marker conflicts with live subvolume: {unexpected_live_stale[:5]}')
        unmarked = [k for k, v in before.items()
                    if k.startswith('0/') and k != '0/5' and
                    int(k.split('/')[1]) not in live_ids and
                    v not in ('<stale>', '<under deletion>', '<squota space holder>')]
        under_deletion = sum(v == '<under deletion>' for v in before.values())
        squota = sum(v == '<squota space holder>' for v in before.values())
        pending_before = pending_deletion_ids(fs)
        pending_stale_before = {q for q in stale if int(q.split('/')[1]) in pending_before}
        available = has_native_clear_stale()
        print(f'mode={mode} filesystem={fs} uuid={uuid} qgroups={len(before)} '
              f'stale_before={len(stale)} under_deletion={under_deletion} '
              f'squota_placeholders={squota} unmarked_orphans={len(unmarked)} '
              f'pending_deletions={len(pending_before)} '
              f'stale_pending={len(pending_stale_before)} '
              f'stale_eligible={len(stale) - len(pending_stale_before)} '
              f'clear_stale_supported={str(available).lower()}', flush=True)
        if not execute:
            print('dry_run=true', flush=True)
            return
        if not available:
            raise Refused('installed btrfs-progs lacks native qgroup clear-stale')
        if squota:
            raise Refused('simple-quota placeholders detected; manual review required')
        if unmarked:
            raise Refused(f'{len(unmarked)} unmarked orphan qgroups: cannot safely automate on this version')
        if len(stale) > max_stale:
            raise Refused(f'{len(stale)} stale qgroups exceed guarded max-stale={max_stale}')
        native = None
        if stale:
            # Native clear-stale is deliberately a single bulk operation. It
            # can remove ordinary stale qgroups while returning rc=1/EBUSY
            # for subvolumes still queued for asynchronous deletion.
            native = command('btrfs', 'qgroup', 'clear-stale', str(fs), check=False)
        after = qgroups(fs)
        pending_after = pending_deletion_ids(fs)
        after_stale = {q for q, path in after.items() if path == '<stale>'}
        changed_nonstale = {q: path for q, path in before.items() if path != '<stale>'}
        if any(after.get(q) != path for q, path in changed_nonstale.items()):
            raise Refused('non-stale qgroup rows changed; inspect concurrent operations')
        # Never declare an unexplained residual stale qgroup acceptable.
        unexplained = {q for q in after_stale
                       if int(q.split('/')[1]) not in pending_after}
        if unexplained:
            raise Refused(f'{len(unexplained)} stale qgroups without pending deletion remain: '
                          f'{sorted(unexplained)[:5]}')
        if native is not None and native.returncode != 0:
            # Do not swallow arbitrary Btrfs errors: only EBUSY on a known
            # queued deletion, corroborated by the post-operation inventory.
            if not expected_busy_errors(native.stderr, pending_before | pending_after):
                raise Refused(f'native clear-stale failed rc={native.returncode}: '
                              f'{native.stderr.strip()[:400]}')
        deferred = len(after_stale)
        removed = len(set(stale) - after_stale)
        outcome = 'deferred_pending' if deferred else 'complete'
        print(f'stale_after={deferred} removed={removed} '
              f'deferred_pending={deferred} pending_deletions_after={len(pending_after)} '
              f'native_rc={native.returncode if native is not None else 0} '
              f'result={outcome} dry_run=false', flush=True)



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='modify Btrfs quota metadata')
    parser.add_argument('--config', default=str(MAINTENANCE_CONFIG),
                        help='root-owned endpoint-specific maintenance configuration')
    args = parser.parse_args(argv)
    try:
        settings = load_maintenance_config(absolute_path(args.config, 'config'))
        run(execute=args.execute, **settings)
        return 0
    except (OSError, Refused, subprocess.SubprocessError) as exc:
        print(f'btrfs-clear-stale-qgroups: REFUSED: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
