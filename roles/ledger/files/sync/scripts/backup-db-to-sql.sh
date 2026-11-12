#!/usr/bin/env bash

set -euo pipefail

# Back up the PostgreSQL database used by the installed Ledger production stack.
# The backup is written under the application's production backup directory.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/compose.yaml"
ENV_FILE="${PROJECT_DIR}/.env"
BACKUP_DIR="${PROJECT_DIR}/backups"
DB_SERVICE="${LEDGER_DB_SERVICE:-ledger-db}"

if [[ ! -f "${COMPOSE_FILE}" || ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: Ledger runtime files are incomplete under ${PROJECT_DIR}." >&2
    exit 1
fi

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

if ! docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    pg_isready --username "${DB_USERNAME}" --dbname "${DB_NAME}" >/dev/null 2>&1; then
    echo "ERROR: PostgreSQL service '${DB_SERVICE}' is not ready." >&2
    exit 1
fi

mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/ledger-production-${TIMESTAMP}.sql"

echo "Creating plain-format Ledger database backup..."
echo "Service:  ${DB_SERVICE}"
echo "Database: ${DB_NAME}"
echo "User:     ${DB_USERNAME}"
echo "Output:   ${BACKUP_FILE}"
echo

if ! docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    pg_dump --format=plain --no-owner --no-privileges --username "${DB_USERNAME}" --dbname "${DB_NAME}" \
    > "${BACKUP_FILE}"; then
    rm -f "${BACKUP_FILE}"
    echo "ERROR: Database backup failed." >&2
    exit 1
fi

if [[ ! -s "${BACKUP_FILE}" ]]; then
    rm -f "${BACKUP_FILE}"
    echo "ERROR: Database backup produced an empty file." >&2
    exit 1
fi

echo "Database backup completed successfully:"
echo "  ${BACKUP_FILE}"
