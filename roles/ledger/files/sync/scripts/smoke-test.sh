#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/compose.yaml"
ENV_FILE="${PROJECT_DIR}/.env"

if [[ ! -f "${COMPOSE_FILE}" || ! -f "${ENV_FILE}" ]]; then
    echo "ERROR: Ledger runtime files are incomplete under ${PROJECT_DIR}." >&2
    exit 1
fi

cd "${PROJECT_DIR}"
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" config --quiet

BASE_URL="${1:-${LEDGER_BASE_URL:-http://localhost/ledger}}"
BASE_URL="${BASE_URL%/}"

expect_code() {
    local expected="$1"
    local url="$2"
    local code

    code="$(curl -ksS -o /dev/null -w '%{http_code}' "${url}")"

    if [[ "${code}" != "${expected}" ]]; then
        echo "ERROR: Expected HTTP ${expected} from ${url}, got ${code}" >&2
        exit 1
    fi

    echo "OK ${expected}: ${url}"
}

check_version_endpoint() {
    local url="$1"
    local expected_component="$2"
    local response

    if ! response="$(curl -ksS "${url}")"; then
        echo "ERROR: Failed to retrieve version information from ${url}" >&2
        exit 1
    fi

    if ! grep -Eq \
        "\"component\"[[:space:]]*:[[:space:]]*\"${expected_component}\"" \
        <<<"${response}"; then
        echo "ERROR: ${url} did not identify component ${expected_component}" >&2
        echo "Response:" >&2
        echo "${response}" >&2
        exit 1
    fi

    if ! grep -Eq \
        '"version"[[:space:]]*:[[:space:]]*"[^"]+"' \
        <<<"${response}"; then
        echo "ERROR: ${url} did not contain a non-empty version" >&2
        echo "Response:" >&2
        echo "${response}" >&2
        exit 1
    fi

    if ! grep -Eq \
        '"gitCommit"[[:space:]]*:[[:space:]]*"[^"]+"' \
        <<<"${response}"; then
        echo "ERROR: ${url} did not contain a non-empty gitCommit" >&2
        echo "Response:" >&2
        echo "${response}" >&2
        exit 1
    fi

    echo "OK: ${url} contains ${expected_component} version metadata"
}

echo "Checking Ledger containers..."
docker compose --file "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps

echo
expect_code 200 "${BASE_URL}/client-health"
expect_code 401 "${BASE_URL}/api/auth/me"

echo
check_version_endpoint \
    "${BASE_URL}/version.json" \
    "ledger-client"

check_version_endpoint \
    "${BASE_URL}/api/version" \
    "ledger-server"

echo
echo "Production smoke test passed."