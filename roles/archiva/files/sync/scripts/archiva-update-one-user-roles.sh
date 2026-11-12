#!/bin/bash
set -u

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. "${SCRIPT_DIR}/snippets/archiva-login.sh"
. "${SCRIPT_DIR}/snippets/archiva-get-role.sh"
. "${SCRIPT_DIR}/snippets/archiva-convert-role-users.sh"
. "${SCRIPT_DIR}/snippets/archiva-update-role-users.sh"
. "${SCRIPT_DIR}/snippets/archiva-get-user.sh"

mkdir -p "${HOME}/temp"
cd "${HOME}/temp" || exit 2
rm -f cookie.txt output.json request-body.json stdout.txt role.json role-update.json user.json

if [ -z "${1:-}" ]; then
    echo "username not specified" >&2
    exit 2
fi
username="$1"

if [ -z "${2:-}" ]; then
    echo "required roles filename not specified" >&2
    exit 2
fi
required_roles_file="$2"

if [ ! -f "$required_roles_file" ]; then
    echo "required roles file not found: $required_roles_file" >&2
    exit 2
fi

if ! jq -e 'type == "array" and all(.[]; type == "string")' "$required_roles_file" >/dev/null 2>&1; then
    echo "required roles file must be a JSON array of strings: $required_roles_file" >&2
    exit 2
fi

archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ "$result" -ne 0 ]; then
    echo "Error: ${0}: archiva_login failed: result=${result}" >&2
    exit 2
fi

archiva_get_user "${username}"
result=$?
if [ "$result" -ne 0 ]; then
    echo "Error: ${0}: archiva_get_user failed for user '${username}': result=${result}" >&2
    exit 2
fi
cp output.json user.json

changed=0

while IFS= read -r role_name; do
    [ -z "$role_name" ] && continue

    archiva_get_role "${role_name}" > role.json
    result=$?
    if [ "$result" -ne 0 ]; then
        echo "Error: ${0}: archiva_get_role failed for role '${role_name}': result=${result}" >&2
        exit 2
    fi

    if jq -e --arg username "$username" 'any((.users // [])[].username; . == $username)' role.json >/dev/null; then
        echo "Role already present for user '${username}': ${role_name}"
        continue
    fi

    echo "Adding user '${username}' to role '${role_name}'"

    archiva_convert_role_users role.json user.json role-update.json
    result=$?
    if [ "$result" -ne 0 ]; then
        echo "Error: ${0}: archiva_convert_role_users failed for role '${role_name}': result=${result}" >&2
        exit 2
    fi

    archiva_update_role_users role-update.json
    result=$?
    if [ "$result" -ne 0 ]; then
        echo "Error: ${0}: archiva_update_role_users failed for role '${role_name}': result=${result}" >&2
        exit 2
    fi

    archiva_get_role "${role_name}" > role.json
    result=$?
    if [ "$result" -ne 0 ]; then
        echo "Error: ${0}: verification archiva_get_role failed for role '${role_name}': result=${result}" >&2
        exit 2
    fi

    if ! jq -e --arg username "$username" 'any((.users // [])[].username; . == $username)' role.json >/dev/null; then
        echo "Error: ${0}: user '${username}' still missing role '${role_name}' after update" >&2
        exit 2
    fi

    changed=1
done < <(jq -r '.[]' "$required_roles_file")

if [ "$changed" -eq 1 ]; then
    echo "Success - changed"
    exit 1
else
    echo "Success - no change needed"
    exit 0
fi