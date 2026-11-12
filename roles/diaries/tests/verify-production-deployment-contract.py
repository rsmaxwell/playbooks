#!/usr/bin/env python3
"""Portable regression checks for the supported production deployment contract."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / "roles/diaries"
SCRIPTS = ROLE / "files/sync/scripts"

OBSOLETE_SCRIPTS = (
    "migration0024ImageCatalogue.sh",
    "step8-freeze-writes.sh",
    "step8-capture-production-database-backup.sh",
    "step9-reconcile-production.sh",
    "step12-compare-reconciliation.py",
    "step12-reconcile-production.sh",
    "step13-capture-production-control.sh",
    "step14-production-deployment.sh",
)

TEMPLATED_SCRIPTS = {
    "start.sh",
    "stop.sh",
    "status.sh",
    "logs.sh",
    "shell-prompt-database.sh",
    "shell-prompt-mosquitto.sh",
    "shell-prompt-responder.sh",
    "shell-prompt-client.sh",
    "shell-prompt-nginx.sh",
}
SUPPORTED_SCRIPTS = {
    "README.md",
    "backup-dataset.sh",
    "backup-db-to-binary.sh",
    "backup-db-to-sql.sh",
    "complete-dataset-manifest.py",
    "complete-dataset-publisher.py",
    "complete-dataset-replication.py",
    "complete-dataset-postflight.py",
    "complete-dataset-restore-stage.py",
    "complete-dataset-verification.py",
    "dataset-backup-manifest.py",
    "production-complete-dataset.py",
    "restore-dataset.sh",
    "restore-db-from-binary.sh",
    "restore-db-from-sql.sh",
}

# Historical-looking names are not automatically forbidden: a genuinely permanent
# command can be admitted only by adding it to both SUPPORTED_SCRIPTS and this
# exact-path exception set with a documented classification. Keep exceptions rare.
APPROVED_FEATURE_STYLE_SCRIPTS: set[str] = set()

FEATURE_STYLE_PATTERNS = (
    re.compile(r"^step\d+(?:[-_.].*)?$", re.IGNORECASE),
    re.compile(r"^(?:verify|test|check|capture|prepare|run)[-_]\d{4}(?:[-_.].*)?$", re.IGNORECASE),
    re.compile(r"^migration\d{4}(?:[-_.].*)?$", re.IGNORECASE),
)


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print(f"PASS: {message}")


def read(relative: str) -> str:
    return (ROLE / relative).read_text(encoding="utf-8")


def acl_user_block(acl: str, username: str) -> str:
    match = re.search(
        rf"(?ms)^user[ \t]+{re.escape(username)}[ \t]*$\n(.*?)(?=^user[ \t]+|\Z)",
        acl,
    )
    if match is None:
        raise AssertionError(f"production Mosquitto ACL has no '{username}' user block")
    return match.group(1)


def feature_style_scripts(names: set[str]) -> list[str]:
    return sorted(
        name
        for name in names
        if name not in APPROVED_FEATURE_STYLE_SCRIPTS
        and any(pattern.match(name) for pattern in FEATURE_STYLE_PATTERNS)
    )


def main() -> int:
    try:
        mosquitto = read("files/sync/config/mosquitto/mosquitto.conf")
        acl = read("files/sync/config/mosquitto/aclfile.txt")
        compose = read("templates/compose.yaml.j2")
        start = read("templates/scripts/start.sh.j2")
        defaults = read("defaults/main.yaml")
        main_tasks = read("tasks/main.yaml")
        responder_config = read("templates/config/responder/responder.json.j2")
        copy_tasks = read("tasks/copy.yaml")
        role_readme = read("README.md")
        scripts_readme = read("files/sync/scripts/README.md")

        require("max_inflight_messages 20" in mosquitto and "max_queued_messages 0" in mosquitto,
                "production broker keeps the complete retained-snapshot flow-control policy")
        require("max_queued_messages 10000" not in mosquitto,
                "production broker has no historical 10,000-message truncation ceiling")
        client_acl = acl_user_block(acl, "diaries-client")
        responder_acl = acl_user_block(acl, "diaries-responder")
        web_acl = acl_user_block(acl, "diaries-web")
        require("topic read diaries/images/+" in client_acl,
                "production diaries-client can read canonical retained Image metadata")
        require("topic readwrite diaries/images/+" in responder_acl,
                "production diaries-responder can publish canonical retained Image metadata")
        require("topic read diaries/images/+" in web_acl,
                "production diaries-web can read canonical retained Image metadata")
        require("Validate retained-snapshot broker flow-control policy" in copy_tasks and
                "max_queued_messages[[:space:]]+0" in copy_tasks,
                "Ansible validates the deployed retained-snapshot broker policy")
        require("subpath: ${DIARIES_NAS_CONTENT_PATH}/${DIARIES_FILES_DIR}" in compose,
                "production Compose keeps /data/files selected by the explicit Files selector")
        require("local.env" not in compose and "local.env" not in start,
                "production Compose/start templates do not load local development overrides")
        require(re.search(r"(?m)^diaries_image_fragment_writes_enabled:\s*true\s*$", defaults) is not None,
                "production ImageFragment authoring gate defaults enabled after 0027 close-out")
        require('"imageFragmentWritesEnabled": {{ diaries_image_fragment_writes_enabled | bool | lower }}' in responder_config,
                "responder config renders the explicit production ImageFragment authoring variable")
        require("diaries_image_fragment_writes_enabled is boolean" in main_tasks,
                "Ansible rejects non-boolean production authoring-gate values")
        require("Validate rendered ImageFragment authoring gate" in copy_tasks and
                '"imageFragmentWritesEnabled": {{ diaries_image_fragment_writes_enabled | bool | lower }}' in copy_tasks,
                "Ansible validates the rendered production authoring-gate value")
        require("diaries_image_fragment_writes_enabled: true" in role_readme and
                "diaries_image_fragment_writes_enabled: false" in role_readme and
                "non-destructive" in role_readme,
                "role documentation defines normal enablement and non-destructive rollback")
        require("one effective database dataset <-> one effective mutable Files root" in role_readme,
                "role documentation records the durable database/Files pairing invariant")
        require("database-only" in scripts_readme.lower() and "matching mutable Files snapshot" in scripts_readme,
                "production operator documentation defines database-only and matched Files backup semantics")
        require("schema-2" in scripts_readme.lower() and ".<backup-id>.partial" in scripts_readme and
                "complete-dataset-manifest.py" in scripts_readme,
                "production operator documentation defines the complete-backup manifest and partial-workspace contract")
        require("backup-dataset.sh" in scripts_readme and "restore-dataset.sh" in scripts_readme and
                "preflight" in scripts_readme and "postflight" in scripts_readme and
                "never invokes a complete restore" in scripts_readme,
                "production operator documentation exposes permanent complete backup/restore commands without automatic restore")
        require("{{ diaries_complete_backup_repository_root }}" in copy_tasks and
                "{{ diaries_complete_restore_state_root }}" in copy_tasks,
                "Ansible creates explicit complete-backup repository and restore-state roots")
        require("diaries_complete_backup_storage_mode: auto" in defaults and
                "required-btrfs" in main_tasks and "full-copy" in main_tasks,
                "production role preserves the historical Step 2 storage-mode contract")
        require('diaries_complete_backup_published_root: "{{ diaries_project_dir }}/data/diaries-backup"' in defaults and
                "diaries_complete_backup_published_root" in main_tasks,
                "production role defines and validates the separate Step 8 stable publication path")
        env_template = read("templates/.env.j2")
        require("DIARIES_COMPLETE_BACKUP_REPOSITORY_ROOT={{ diaries_complete_backup_repository_root }}" in env_template and
                "DIARIES_COMPLETE_RESTORE_STATE_ROOT={{ diaries_complete_restore_state_root }}" in env_template and
                "DIARIES_COMPLETE_BACKUP_PUBLISHED_ROOT={{ diaries_complete_backup_published_root }}" in env_template and
                "DIARIES_COMPLETE_BACKUP_STORAGE_MODE={{ diaries_complete_backup_storage_mode }}" in env_template,
                "production .env carries the explicit complete-dataset storage and publication contract")
        require(
            "temporary feature-only production helper" in scripts_readme.lower()
            and "explicitly deployed" in scripts_readme.lower()
            and "explicitly removed" in scripts_readme.lower(),
            "production operator documentation defines temporary helper deploy/remove lifecycle",
        )

        present = {p.name for p in SCRIPTS.iterdir() if p.is_file()}
        require(present == SUPPORTED_SCRIPTS,
                "role source contains only the approved supported production script set")
        require(
            not feature_style_scripts(present),
            "role source contains no unclassified feature/step-shaped production helpers",
        )
        synthetic = set(SUPPORTED_SCRIPTS) | {"step99-capture-example.sh"}
        require(
            feature_style_scripts(synthetic) == ["step99-capture-example.sh"],
            "production recurrence policy detects a newly accumulated stepN helper",
        )
        require(all(not (SCRIPTS / name).exists() for name in OBSOLETE_SCRIPTS),
                "completed-feature production helpers are absent from role source")
        require(all(name not in copy_tasks for name in OBSOLETE_SCRIPTS),
                "one-off obsolete-script removal lists are no longer required")

        project_marker = "- name: diaries:copy | Synchronize project files excluding managed scripts"
        scripts_marker = "- name: diaries:copy | Synchronize managed scripts"
        require(project_marker in copy_tasks and scripts_marker in copy_tasks,
                "Ansible has separate project-root and managed-scripts synchronization tasks")
        project_sync = copy_tasks.split(project_marker, 1)[1].split("\n- name:", 1)[0]
        scripts_sync = copy_tasks.split(scripts_marker, 1)[1].split("\n- name:", 1)[0]

        require('src: "sync/"' in project_sync and '--exclude=/scripts/' in project_sync,
                "project-root synchronization excludes the separately managed scripts directory")
        require(re.search(r'^\s*-\s+"--delete"\s*$', project_sync, re.MULTILINE) is None,
                "project-root synchronization does not use rsync --delete")
        require('src: "sync/scripts/"' in scripts_sync and
                'dest: "{{ diaries_project_dir }}/scripts/"' in scripts_sync,
                "production scripts are synchronized as their own managed directory")
        require(re.search(r'^\s*-\s+"--delete"\s*$', scripts_sync, re.MULTILINE) is not None and
                re.search(r'^\s*-\s+"--delete-excluded"\s*$', scripts_sync, re.MULTILINE) is not None,
                "managed scripts synchronization removes unmanaged and excluded destination entries")
        require('--exclude=__pycache__/' in scripts_sync and '--exclude=*.pyc' in scripts_sync,
                "managed scripts synchronization excludes transient Python interpreter caches")
        for name in sorted(TEMPLATED_SCRIPTS):
            require(f'--filter=protect_/{name}' in scripts_sync,
                    f"managed scripts synchronization protects templated permanent script {name}")
    except (AssertionError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print("PASS: production deployment contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
