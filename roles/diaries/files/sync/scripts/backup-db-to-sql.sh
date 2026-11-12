#!/usr/bin/env bash

set -euo pipefail

# Back up the PostgreSQL database used by the installed Diaries production stack.
# The backup is written under the application's production backup directory.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/compose.yaml"
ENV_FILE="${PROJECT_DIR}/.env"
BACKUP_DIR="${PROJECT_DIR}/data/database-backups/production"
DB_SERVICE="${DIARIES_DB_SERVICE:-diaries-db}"
MANIFEST_TOOL="${SCRIPT_DIR}/dataset-backup-manifest.py"

if [[ ! -f "${COMPOSE_FILE}" || ! -f "${ENV_FILE}" || ! -x "${MANIFEST_TOOL}" ]]; then
    echo "ERROR: Diaries runtime files are incomplete under ${PROJECT_DIR}." >&2
    exit 1
fi

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

if ! docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    pg_isready --username "${DB_USERNAME}" --dbname "${DB_NAME}" >/dev/null 2>&1; then
    echo "ERROR: PostgreSQL service '${DB_SERVICE}' is not ready." >&2
    exit 1
fi

mkdir -p "${BACKUP_DIR}"
TIMESTAMP="$(date '+%Y%m%d-%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/diaries-production-${TIMESTAMP}.sql"

echo "Operation: DATABASE-ONLY backup"
echo "Effective dataset: ${DIARIES_DATASET_NAME}"
echo "Database storage:  ${DIARIES_EFFECTIVE_DB_DATA}"
echo "Files selector:    ${DIARIES_EFFECTIVE_FILES_DIR}"
echo "Files root:        ${DIARIES_EFFECTIVE_FILES_ROOT}"
echo "Complete dataset:  NO - mutable Files bytes are not included."
echo

echo "Creating plain-format Diaries database backup..."
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

IMAGE_ROW_COUNT="$(docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" exec -T "${DB_SERVICE}" \
    psql -X -A -t --username "${DB_USERNAME}" --dbname "${DB_NAME}" -c 'SELECT count(*) FROM public.image;' 2>/dev/null | tr -d '[:space:]' || true)"
[[ -n "${IMAGE_ROW_COUNT}" ]] || IMAGE_ROW_COUNT=unknown
RUNTIME_IMAGES="$(docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" config --images 2>/dev/null || true)"
MANIFEST_FILE="$(python3 "${MANIFEST_TOOL}" write --project-dir "${PROJECT_DIR}" --backup-file "${BACKUP_FILE}" --backup-format "plain-sql" --image-row-count "${IMAGE_ROW_COUNT}" --runtime-images "${RUNTIME_IMAGES}")"

echo "Database backup completed successfully:"
echo "  ${BACKUP_FILE}"
echo "Manifest: ${MANIFEST_FILE}"
echo "NOTE: This is not a complete dataset backup; preserve the matching Files snapshot separately."
