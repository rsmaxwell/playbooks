#!/usr/bin/env python3
"""0034 Step 9 regression for explicit production capture/publication wiring."""
from pathlib import Path
import importlib.util
import sys
import tempfile

ROLE = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROLE / 'files/sync/scripts/production-complete-dataset.py'
WRAPPER = ROLE / 'files/sync/scripts/backup-dataset.sh'
failures = []


def check(ok, message):
    if ok:
        print('PASS:', message)
    else:
        failures.append(message)
        print('FAIL:', message)


def load_engine():
    spec = importlib.util.spec_from_file_location('step9_engine', ENGINE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exercise_cli(module, args, *, fail_publish=False):
    calls = []
    class FakeProduction:
        env = {'DIARIES_0036_ROLLING_ENABLED': 'false',
               'DIARIES_0036_INCREMENTAL_NAS_ENABLED': 'false'}
    fake = FakeProduction()
    backup_path = Path('/srv/legacy/20261009-150000Z')

    original = {
        'Production': module.Production,
        'backup_complete': module.backup_complete,
        'publisher_preflight': module.publisher_preflight,
        'publish_completed_backup': module.publish_completed_backup,
    }
    try:
        module.Production = lambda _script_dir: fake

        def fake_backup(p, *, preflight, requested_id=None, rolling=False, incremental=False, held_lock_fd=None):
            assert p is fake
            calls.append(('backup', preflight, requested_id))
            assert rolling is False and incremental is False and held_lock_fd is None
            return None if preflight else backup_path

        def fake_preflight(p):
            assert p is fake
            calls.append(('publisher-preflight',))

        def fake_publish(p, backup, *, rolling=False, held_lock_fd=None):
            assert p is fake
            calls.append(('publish', backup))
            assert rolling is False and held_lock_fd is None
            if fail_publish:
                raise module.ToolError('synthetic publication failure')

        module.backup_complete = fake_backup
        module.publisher_preflight = fake_preflight
        module.publish_completed_backup = fake_publish
        rc = module.main(['production-complete-dataset.py', 'backup', *args])
        return rc, calls
    finally:
        for name, value in original.items():
            setattr(module, name, value)


def main():
    engine = ENGINE_PATH.read_text()
    wrapper = WRAPPER.read_text()
    check('exec python3 "${SCRIPT_DIR}/production-complete-dataset.py" backup "$@"' in wrapper,
          'permanent backup wrapper still delegates all modes through the production engine')
    check('def publisher_preflight(p: Production)' in engine and
          'def publish_completed_backup(p: Production, backup: Path, *, rolling: bool = False,' in engine,
          'production engine has explicit publisher preflight and completed-backup publication helpers')
    check('"publish-preflight"' in engine and '"publish"' in engine,
          'production backup CLI exposes explicit Step 9 publish modes')
    check('Legacy backup kept:' in engine,
          'publication output explicitly records preservation of the legacy timestamp-ID backup')

    module = load_engine()
    with tempfile.TemporaryDirectory(prefix='step9-published-root-') as temp:
        base = Path(temp)
        generations = base / '.diaries-backup-generations'
        (generations / '20261009-153243Z').mkdir(parents=True)
        (base / 'diaries-backup').symlink_to(
            '.diaries-backup-generations/20261009-153243Z', target_is_directory=True)
        prod = module.Production.__new__(module.Production)
        prod.env = {'DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT': str(base / 'diaries-backup')}
        configured = prod._configured_absolute_path('DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT')
        check(configured == base / 'diaries-backup' and configured.name == 'diaries-backup',
              'configured stable publication path is preserved after symlink points to a generation')
    rc, calls = exercise_cli(module, [])
    check(rc == 0 and calls == [('backup', False, None)],
          'plain backup keeps frozen 0033 capture-only behaviour')

    rc, calls = exercise_cli(module, ['preflight'])
    check(rc == 0 and calls == [('backup', True, None)],
          'plain preflight keeps frozen 0033 capture-only preflight behaviour')

    rc, calls = exercise_cli(module, ['publish-preflight'])
    check(rc == 0 and calls == [('publisher-preflight',), ('backup', True, None)],
          'publish-preflight checks publication layout before non-mutating live capture preflight')

    rc, calls = exercise_cli(module, ['publish'])
    check(rc == 0 and calls == [
        ('publisher-preflight',),
        ('backup', False, None),
        ('publish', Path('/srv/legacy/20261009-150000Z')),
    ], 'publish mode preflights, creates the immutable legacy backup, then publishes exactly that completed backup')

    rc, calls = exercise_cli(module, ['publish'], fail_publish=True)
    check(rc == 1 and calls[:2] == [('publisher-preflight',), ('backup', False, None)] and
          calls[2:] == [('publish', Path('/srv/legacy/20261009-150000Z'))],
          'publication failure is surfaced only after the completed legacy backup exists')

    if failures:
        print(f'FAILED: {len(failures)} Step 9 publication wiring check(s)', file=sys.stderr)
        return 1
    print('PASS: 0034 Step 9 production publication wiring contract')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
