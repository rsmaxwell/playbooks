#!/usr/bin/env bash

set -euo pipefail

# Restore the installed Diaries production database from a PostgreSQL custom-format dump.
#
# Usage:
#   restore-db-from-binary.sh [backup-file]
#
# A supplied relative filename is resolved beneath the production backup
# directory used by backup-db-to-binary.sh. An absolute path is used unchanged.
# If no file is supplied, the newest standard dump backup in that directory is
# selected. The diaries-responder service is stopped during the restore if it
# was running and is restarted only after success.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/compose.yaml"
ENV_FILE="${PROJECT_DIR}/.env"
BACKUP_DIR="${PROJECT_DIR}/data/database-backups/production"
DB_SERVICE="${DIARIES_DB_SERVICE:-diaries-db}"
MANIFEST_TOOL="${SCRIPT_DIR}/dataset-backup-manifest.py"
APPLICATION_SERVICE="${DIARIES_RESPONDER_SERVICE:-diaries-responder}"

if [[ $# -gt 1 ]]; then
    echo "Usage: $(basename -- "$0") [backup-file]" >&2
    exit 1
fi
if [[ ! -f "${COMPOSE_FILE}" || ! -f "${ENV_FILE}" || ! -x "${MANIFEST_TOOL}" ]]; then
    echo "ERROR: Diaries runtime files are incomplete under ${PROJECT_DIR}." >&2
    exit 1
fi

if [[ $# -eq 1 ]]; then
    if [[ "$1" = /* ]]; then
        BACKUP_FILE="$1"
    else
        BACKUP_FILE="${BACKUP_DIR}/$1"
    fi
else
    BACKUP_FILE="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'diaries-production-*.dump' -printf '%T@ %p
' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
fi

if [[ -z "${BACKUP_FILE:-}" || ! -f "${BACKUP_FILE}" ]]; then
    echo "ERROR: Database backup file was not found." >&2
    exit 1
fi
if [[ ! -s "${BACKUP_FILE}" ]]; then
    echo "ERROR: Database backup file is empty: ${BACKUP_FILE}" >&2
    exit 1
fi
BACKUP_FILE="$(cd -- "$(dirname -- "${BACKUP_FILE}")" && pwd)/$(basename -- "${BACKUP_FILE}")"

cd "${PROJECT_DIR}"
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" config --quiet

DATASET_CONTEXT="$(python3 "${MANIFEST_TOOL}" describe --project-dir "${PROJECT_DIR}" --shell)"
eval "${DATASET_CONTEXT}"

if ! docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps --status running --services | grep -Fxq "${DB_SERVICE}"; then
    echo "ERROR: Database service '${DB_SERVICE}' is not running." >&2
    exit 1
fi

DB_NAME="$(docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" printenv POSTGRES_DB)"
DB_USERNAME="$(docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" printenv POSTGRES_USER)"
if [[ -z "${DB_NAME}" || -z "${DB_USERNAME}" ]]; then
    echo "ERROR: POSTGRES_DB or POSTGRES_USER is not defined in service '${DB_SERVICE}'." >&2
    exit 1
fi
if ! docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" pg_isready --username "${DB_USERNAME}" --dbname postgres >/dev/null 2>&1; then
    echo "ERROR: PostgreSQL service '${DB_SERVICE}' is not ready." >&2
    exit 1
fi

if ! docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" pg_restore --list < "${BACKUP_FILE}" >/dev/null; then
    echo "ERROR: Selected file is not a valid PostgreSQL custom-format dump: ${BACKUP_FILE}" >&2
    exit 1
fi

python3 "${MANIFEST_TOOL}" verify --project-dir "${PROJECT_DIR}" --backup-file "${BACKUP_FILE}"

echo
echo "Operation: DATABASE-ONLY restore"
echo "Effective dataset: ${DIARIES_DATASET_NAME}"
echo "Database storage:  ${DIARIES_EFFECTIVE_DB_DATA}"
echo "Files selector:    ${DIARIES_EFFECTIVE_FILES_DIR}"
echo "Files root:        ${DIARIES_EFFECTIVE_FILES_ROOT}"
echo "Complete restore:  NO - mutable Files bytes will not be restored."
echo

cat <<MSG
WARNING: This will completely replace the PRODUCTION Diaries database.

Database: ${DB_NAME}
Backup:   ${BACKUP_FILE}
MSG
read -r -p "Type RESTORE to continue: " ANSWER
if [[ "${ANSWER}" != "RESTORE" ]]; then
    echo "Restore cancelled."
    exit 0
fi

APPLICATION_WAS_RUNNING=false
if docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps --status running --services | grep -Fxq "${APPLICATION_SERVICE}"; then
    APPLICATION_WAS_RUNNING=true
    echo "Stopping ${APPLICATION_SERVICE} during restore..."
    docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" stop "${APPLICATION_SERVICE}"
fi

restore_application() {
    if [[ "${APPLICATION_WAS_RUNNING}" == true ]]; then
        echo "Starting ${APPLICATION_SERVICE}..."
        docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up --detach "${APPLICATION_SERVICE}"
    fi
}
trap restore_application EXIT

echo "Terminating existing connections..."
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    psql -X -v ON_ERROR_STOP=1 --username "${DB_USERNAME}" --dbname postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();"

echo "Dropping existing database..."
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    dropdb --if-exists --username "${DB_USERNAME}" "${DB_NAME}"

echo "Creating empty database..."
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    createdb --username "${DB_USERNAME}" --owner "${DB_USERNAME}" "${DB_NAME}"

echo "Restoring database..."
if ! docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    pg_restore --exit-on-error --no-owner --no-privileges --username "${DB_USERNAME}" --dbname "${DB_NAME}" < "${BACKUP_FILE}"; then
    echo "ERROR: Database restore failed; ${APPLICATION_SERVICE} has been left stopped." >&2
    APPLICATION_WAS_RUNNING=false
    exit 1
fi

echo "Database restore completed successfully."
