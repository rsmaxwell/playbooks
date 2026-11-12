#!/usr/bin/env bash

set -euo pipefail

# Reset the installed Ledger PostgreSQL data directory and recreate the stack.
# This is destructive and is intended only for an explicit production reset.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/compose.yaml"
ENV_FILE="${PROJECT_DIR}/.env"
DATA_DIR="${PROJECT_DIR}/data/postgres"

if [[ ! -f "${COMPOSE_FILE}" || ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: Ledger runtime files are incomplete under ${PROJECT_DIR}." >&2
    exit 1
fi

cat <<MSG
WARNING: This will permanently delete the installed Ledger PostgreSQL data.

Data directory:
  ${DATA_DIR}
MSG
read -r -p "Type RESET to continue: " ANSWER
if [[ "${ANSWER}" != "RESET" ]]; then
    echo "Reset cancelled."
    exit 0
fi

cd "${PROJECT_DIR}"
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" down --remove-orphans
sudo rm -rf -- "${DATA_DIR}"
mkdir -p "${DATA_DIR}"
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" up --detach --remove-orphans --wait

echo "Ledger database reset completed successfully."
