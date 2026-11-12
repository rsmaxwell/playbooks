#!/usr/bin/env bash

set -euo pipefail

# Restore the installed Ledger production database from a PostgreSQL custom-format dump.
#
# Usage:
#   restore-db.sh [backup-file]
#
# If no file is supplied, the newest standard dump backup in the production
# backup directory is selected. The ledger-server service is stopped during
# the restore if it was running and is restarted only after success.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/compose.yaml"
ENV_FILE="${PROJECT_DIR}/.env"
BACKUP_DIR="${PROJECT_DIR}/backups"
DB_SERVICE="${LEDGER_DB_SERVICE:-ledger-db}"
APPLICATION_SERVICE="${LEDGER_SERVER_SERVICE:-ledger-server}"

if [[ $# -gt 1 ]]; then
    echo "Usage: $(basename -- "$0") [backup-file]" >&2
    exit 1
fi
if [[ ! -f "${COMPOSE_FILE}" || ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: Ledger runtime files are incomplete under ${PROJECT_DIR}." >&2
    exit 1
fi

CALLER_DIR="$(pwd)"
if [[ $# -eq 1 ]]; then
    if [[ "$1" = /* ]]; then
        BACKUP_FILE="$1"
    elif [[ -f "${CALLER_DIR}/$1" ]]; then
        BACKUP_FILE="${CALLER_DIR}/$1"
    else
        BACKUP_FILE="${BACKUP_DIR}/$1"
    fi
else
    BACKUP_FILE="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name 'ledger-production-*.dump' -printf '%T@ %p
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

cat <<MSG
WARNING: This will completely replace the PRODUCTION Ledger database.

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
