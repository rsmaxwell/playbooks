#!/usr/bin/env python3
"""Disposable 0036 transaction rehearsal. Never accesses production Docker/NAS.

Uses real rsync, schema-2 manifest validator and linked publisher; synthetic DB.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'files/sync/scripts'
PUBLISHER = SCRIPTS / 'complete-dataset-publisher.py'
fixture = HERE / 'verify-complete-dataset-manifest.py'
source = fixture.read_text()
ns = {'__name__': 'fixture_0036', '__file__': str(fixture)}
exec(compile(source[:source.index('def mutate_manifest(')], str(fixture), 'exec'), ns)

def run(*argv, check=True, pass_fds=()):
    result = subprocess.run(list(map(str,argv)), capture_output=True, text=True, pass_fds=pass_fds)
    if check and result.returncode:
        raise AssertionError(f'{argv}: {result.stderr}\n{result.stdout}')
    return result

def pub(root, action, *args, fd=None, check=True):
    cmd = [sys.executable, PUBLISHER, '--published-root', root]
    if fd is not None:
        cmd += ['--held-lock-fd', str(fd)]
    cmd += [action, *args]
    return run(*cmd, pass_fds=(fd,) if fd is not None else (), check=check)

def ok(expression, name):
    assert expression, name
    print('PASS:', name, flush=True)

def fingerprint(path):
    return {p.relative_to(path).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}

def candidate(base, backup_id):
    partial = ns['create_candidate'](base)
    target = base / ('.' + backup_id + '.partial')
    partial.rename(target)
    return target

def finalise(partial, backup_id):
    file_entries = []
    for path in sorted((partial / 'files').rglob('*')):
        if path.is_file():
            file_entries.append({'path': path.relative_to(partial).as_posix(),
                                 'sizeBytes': path.stat().st_size,
                                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    inventory = {'schemaVersion': 1, 'root': 'files', 'fileCount': len(file_entries),
                 'totalBytes': sum(e['sizeBytes'] for e in file_entries), 'files': file_entries}
    (partial / 'verification/inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    (partial / 'verification/files.sha256').write_text(''.join(
        f"{e['sha256']}  {e['path']}\n" for e in file_entries))
    result = ns['write_manifest'](partial)
    assert result.returncode == 0, result.stderr
    final = partial.parent / backup_id
    partial.rename(final)
    return final

def sync(live, previous, dest):
    uid, gid = os.getuid(), os.getgid()
    args = ['-rptcog', f'--chown={uid}:{gid}', '--exclude=/.image-staging/']
    run('rsync', *args, f'--link-dest={previous}/', str(live)+'/',str(dest)+'/')
    delta = run('rsync', '-rptcogni', f'--chown={uid}:{gid}', '--delete',
                '--exclude=/.image-staging/', str(live)+'/', str(dest)+'/')
    assert not delta.stdout.strip(), delta.stdout


def main():
    if not shutil.which('rsync'):
        raise SystemExit('FAIL: rsync is required')
    with tempfile.TemporaryDirectory(prefix='0036-disposable-') as tmp:
        root = Path(tmp); inputs = root / 'inputs'; inputs.mkdir()
        published = root / 'diaries-backup'
        first_id, second_id = '20261015-120000Z', '20261015-130000Z'
        initial = finalise(candidate(inputs, first_id), first_id)
        pub(published, 'create-linked', initial)
        ok(pub(published, 'verify-current').returncode == 0, 'initial verified publication')
        previous = published.resolve(strict=True)
        before = fingerprint(previous)
        live = root / 'synthetic-nas'; shutil.copytree(previous/'files', live)
        (live/'a.txt').write_text('updated alpha\n')
        (live/'new.txt').write_text('new file\n')
        (live/'nested/b.bin').unlink()
        (live/'.image-staging').mkdir()
        (live/'.image-staging'/'excluded').write_text('transient')
        lock_file = root/'.diaries-backup.lock'
        with lock_file.open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            fd = lock.fileno()
            pub(published, 'verify-current', fd=fd)
            # An independent publisher cannot acquire the transaction lock.
            contender = subprocess.Popen([sys.executable, str(PUBLISHER),
                '--published-root', str(published), 'verify-current'],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                try:
                    contender.communicate(timeout=.4)
                    raise AssertionError('competing publisher did not block')
                except subprocess.TimeoutExpired:
                    ok(True, 'publisher blocked while transaction holds lock')
            finally:
                contender.kill(); contender.communicate()
            failed = candidate(inputs, '20261015-123000Z')
            shutil.rmtree(failed/'files'); (failed/'files').mkdir()
            # Deliberately simulate an interrupted transfer after first file.
            (failed/'files'/'partial.bin').write_bytes(b'incomplete')
            ok(published.resolve() == previous and fingerprint(previous) == before,
               'interrupted unpublished candidate leaves accepted generation intact')
            shutil.rmtree(failed)
            next_partial = candidate(inputs, second_id)
            shutil.rmtree(next_partial/'files'); (next_partial/'files').mkdir()
            sync(live, previous/'files', next_partial/'files')
            ok((next_partial/'files'/'new.txt').is_file() and
               not (next_partial/'files'/'nested/b.bin').exists() and
               not (next_partial/'files'/'.image-staging').exists(),
               'changed/add/delete and transient staging excluded')
            # Identical files would be linked; fixture's a.txt deliberately changed.
            new_final = finalise(next_partial, second_id)
            pub(published, 'create-linked', new_final, fd=fd)
            ok(pub(published, 'verify-current', fd=fd).returncode == 0 and
               pub(published, 'show-current-id', fd=fd).stdout.strip() == second_id,
               'atomic publication and schema-2 verification under inherited lock')
            ok(fingerprint(previous) == before,
               'previous accepted generation unchanged after retry')
            fcntl.flock(lock, fcntl.LOCK_UN)
        ok(pub(published, 'verify-current').returncode == 0,
           'publisher available after transaction lock release')
    print('PASS: 0036 disposable transaction rehearsal (host/synthetic, NOT pluto Docker/NAS)')

if __name__ == '__main__':
    main()
