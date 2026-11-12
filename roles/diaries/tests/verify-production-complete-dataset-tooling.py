#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import subprocess
import sys

ROLE = Path(__file__).resolve().parents[1]
SCRIPTS = ROLE / 'files' / 'sync' / 'scripts'

EXPECTED_SHARED_HASHES = {
    'complete-dataset-manifest.py': 'd9490f706f427b11a5b5758b9a818e3218aa0624e5e659ea6187b2518fdfbc73',
    'complete-dataset-verification.py': 'b278b72383f3bae5c6ec95e2b17cc0ce12d2f3377b4f781626880484d426400a',
    'complete-dataset-restore-stage.py': 'c6e9272191363c06e988d1ea849bdb57e44ac3408e74d65895aa2f9c2828cfc7',
    'complete-dataset-postflight.py': '7e04b08b033f2f98a70832248c3e60d0ea11bc03b7121852d482b396fe8ec95b',
}


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f'PASS: {message}')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    try:
        backup = SCRIPTS / 'backup-dataset.sh'
        restore = SCRIPTS / 'restore-dataset.sh'
        engine = SCRIPTS / 'production-complete-dataset.py'
        for path in [backup, restore, engine, *[SCRIPTS / n for n in EXPECTED_SHARED_HASHES]]:
            check(path.is_file(), f'production complete-dataset tooling file exists: {path.name}')
            check(bool(path.stat().st_mode & stat.S_IXUSR), f'production tooling is executable in role source: {path.name}')

        subprocess.run(['bash', '-n', str(backup), str(restore)], check=True)
        subprocess.run([sys.executable, '-m', 'py_compile', str(engine),
                        *[str(SCRIPTS / n) for n in EXPECTED_SHARED_HASHES]], check=True)
        check(True, 'production shell/Python complete-dataset tooling parses successfully')

        for name, expected in EXPECTED_SHARED_HASHES.items():
            check(sha(SCRIPTS / name) == expected,
                  f'{name} matches the accepted production schema/inventory helper'

        text = engine.read_text(encoding='utf-8')
        for required in [
            'DIARIES_NAS_CONTENT_PATH', 'DIARIES_FILES_DIR', '"docker", "compose"',
            'DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT', 'DIARIES_COMPLETE_RESTORE_STATE_ROOT',
            'DIARIES_COMPLETE_BACKUP_STORAGE_MODE',
            'docker-compose-service-stop', 'database/diaries.dump', 'database/diaries.sql',
            'complete-dataset-manifest.py', 'complete-dataset-verification.py',
            'complete-dataset-restore-stage.py', 'complete-dataset-postflight.py',
            'Type RESTORE', 'Type APPLY', 'automaticRollbackAvailable',
            'dropdb', 'pg_restore', 'synchronise: ok', 'diaries/marquees/', 'diaries/images/',
            'http://localhost:8081/files/', 'mv "$live" "$rollback"', 'mv "$stage" "$live"',
        ]:
            check(required in text, f'production complete-dataset engine contains required contract: {required}')

        check('dc("stop", DB_SERVICE' not in text and "stop', DB_SERVICE" not in text,
              'complete-dataset tooling never stops PostgreSQL as a writer-quiescence action')
        check('p.stop_responder()' in text and 'p.start_responder()' in text,
              'complete-dataset tooling explicitly quiesces/restores the responder service')
        check('source_verify = partial / ".source-verify"' in text,
              'production backup independently rereads quiesced Files before schema-2 promotion')
        check('HOST_UID' in text and 'HOST_GID' in text and
              'chown -R "$HOST_UID:$HOST_GID" /backup/files' in text and
              'chown -R "$HOST_UID:$HOST_GID" /out' in text,
              'root maintenance copies return host backup/verification trees to the invoking operator ownership')
        check('rm -rf /backup/files/.image-staging' in text and
              'rm -rf /out/.image-staging' in text and
              'transient .image-staging leaked into captured Files snapshot' in text,
              'production backup defensively excludes transient .image-staging from host-side snapshots')
        check(text.count('set -o pipefail') >= 4,
              'production tar data-plane pipelines propagate source/extraction failures')
        check('p.pg_restore_list(backup / "database" / "diaries.dump")' in text,
              'production restore preflight structurally validates the custom dump before destructive work')
        check('p.restore_database(backup / "database" / "diaries.dump")' in text and
              'restore_database(backup / "database" / "diaries.sql")' not in text,
              'production apply restores only the custom dump and never reapplies the SQL companion')
        check('copy_backup_to_stage' in text and 'verify_tree_against_backup' in text,
              'production restore stages and independently verifies replacement Files before apply')
        check('rollback_files' in text and 'safetyBackup' in text,
              'production restore retains executable database+Files rollback semantics')

        copy_tasks = (ROLE / 'tasks' / 'copy.yaml').read_text(encoding='utf-8')
        all_tasks = '\n'.join(path.read_text(encoding='utf-8') for path in (ROLE / 'tasks').glob('*.yaml'))
        check('restore-dataset.sh' not in all_tasks and 'backup-dataset.sh' not in all_tasks,
              'routine Ansible role execution deploys complete-dataset tools but never invokes them')
        check('{{ diaries_complete_backup_repository_root }}' in copy_tasks and
              '{{ diaries_complete_restore_state_root }}' in copy_tasks,
              'Ansible creates the configured complete backup repository and restore-state roots')
        env = (ROLE / 'templates' / '.env.j2').read_text(encoding='utf-8')
        check('DIARIES_FILES_DIR={{ diaries_files_dir }}' in env,
              'production complete-dataset identity remains driven by explicit diaries_files_dir')
        check('DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT={{ diaries_complete_backup_repository_root }}' in env and
              'DIARIES_COMPLETE_RESTORE_STATE_ROOT={{ diaries_complete_restore_state_root }}' in env and
              'DIARIES_COMPLETE_BACKUP_STORAGE_MODE={{ diaries_complete_backup_storage_mode }}' in env,
              'production .env renders the explicit 0034 complete-dataset storage contract')
        check('self.project / "data" / "dataset-backups"' not in text and
              'self.project / "data" / "dataset-restores"' not in text,
              'production complete-dataset engine no longer infers repository/state roots from project layout')
        compose = (ROLE / 'templates' / 'compose.yaml.j2').read_text(encoding='utf-8')
        check('subpath: ${DIARIES_NAS_CONTENT_PATH}/${DIARIES_FILES_DIR}' in compose,
              'production responder still mounts the explicit Files selector at /data/files')

        db_backup = (SCRIPTS / 'backup-db-to-binary.sh').read_text(encoding='utf-8')
        db_restore = (SCRIPTS / 'restore-db-from-binary.sh').read_text(encoding='utf-8')
        check('Operation: DATABASE-ONLY backup' in db_backup and 'Complete dataset:  NO' in db_backup,
              'existing production binary backup remains explicitly database-only')
        check('Operation: DATABASE-ONLY restore' in db_restore and 'Complete restore:  NO' in db_restore,
              'existing production binary restore remains explicitly database-only')
    except (AssertionError, OSError, subprocess.CalledProcessError) as exc:
        print(f'FAIL: {exc}', file=sys.stderr)
        return 1
    print('PASS: production complete-dataset Step-8 tooling contract verified')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
