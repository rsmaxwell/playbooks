#!/usr/bin/env python3
"""0034 Step 8 stable publication configuration/path-isolation regression."""
from pathlib import Path
import importlib.util
import sys

ROLE = Path(__file__).resolve().parents[1]
failures = []

def check(ok, message):
    if ok:
        print('PASS:', message)
    else:
        failures.append(message); print('FAIL:', message)

def read(rel): return (ROLE / rel).read_text()

def main():
    defaults = read('defaults/main.yaml')
    env = read('templates/.env.j2')
    tasks = read('tasks/main.yaml')
    copy_tasks = read('tasks/copy.yaml')
    engine_path = ROLE / 'files/sync/scripts/production-complete-dataset.py'
    engine = engine_path.read_text()
    check('diaries_complete_backup_published_root: "{{ diaries_project_dir }}/data/diaries-backup"' in defaults,
          'stable publication has an explicit default separate from the legacy repository')
    check('DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT={{ diaries_complete_backup_published_root }}' in env,
          'stable publication path is rendered into production .env')
    check('diaries_complete_backup_published_root is match' in tasks and
          'not diaries_complete_backup_published_root.startswith(diaries_complete_backup_repository_root' in tasks,
          'Ansible rejects overlapping publication/repository paths')
    check('DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT={{ diaries_complete_backup_published_root }}' in copy_tasks,
          'deployment verifies the rendered stable publication path in .env')
    check('self.published_root = self._configured_absolute_path("DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT")' in engine,
          'runtime consumes the explicit stable publication path')
    check('backup = p.published_root.resolve()' in engine,
          'diaries-backup restore selector resolves only through the stable publication input')

    spec = importlib.util.spec_from_file_location('step8_engine', engine_path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    Production, ToolError = module.Production, module.ToolError
    def valid(repo, restore, published):
        obj = Production.__new__(Production)
        obj.storage_mode = 'full-copy'
        obj.backup_root = Path(repo); obj.restore_root = Path(restore); obj.published_root = Path(published)
        obj.context = {'files_root': '/srv/live-files'}
        try: obj._validate_complete_storage_contract(); return True
        except ToolError: return False
    check(valid('/srv/legacy', '/srv/state', '/srv/current/diaries-backup'), 'runtime accepts storage/publication roots isolated from source Files')
    for values in [
        ('/srv/legacy','/srv/state','/srv/legacy'),
        ('/srv/legacy','/srv/state','/srv/legacy/diaries-backup'),
        ('/srv/legacy','/srv/state','/srv/state/current'),
        ('/srv/legacy/current','/srv/state','/srv/legacy'),
    ]:
        check(not valid(*values), f'runtime rejects overlapping roots {values}')
    check(not valid('/srv/legacy', '/srv/state', '/srv/live-files/diaries-backup'),
          'runtime rejects stable publication overlapping the mutable source Files root')
    if failures:
        print(f'FAILED: {len(failures)} Step 8 publication contract check(s)', file=sys.stderr); return 1
    print('PASS: 0034 Step 8 stable publication configuration contract')
    return 0

if __name__ == '__main__': raise SystemExit(main())
