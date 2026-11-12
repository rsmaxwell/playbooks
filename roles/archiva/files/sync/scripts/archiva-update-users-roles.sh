#!/bin/bash
set -u

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

single_user_script="${SCRIPT_DIR}/archiva-update-one-user-roles.sh"

if [ ! -x "$single_user_script" ]; then
    echo "single-user script not found or not executable: $single_user_script" >&2
    exit 2
fi

if [ -z "${1:-}" ]; then
    echo "users filename not specified" >&2
    exit 2
fi
users_file="$1"

if [ -z "${2:-}" ]; then
    echo "required roles filename not specified" >&2
    exit 2
fi
required_roles_file="$2"

if [ ! -f "$users_file" ]; then
    echo "users file not found: $users_file" >&2
    exit 2
fi

if [ ! -f "$required_roles_file" ]; then
    echo "required roles file not found: $required_roles_file" >&2
    exit 2
fi

if ! jq -e 'type == "array" and all(.[]; type == "string")' "$users_file" >/dev/null 2>&1; then
    echo "users file must be a JSON array of strings: $users_file" >&2
    exit 2
fi

if ! jq -e 'type == "array" and all(.[]; type == "string")' "$required_roles_file" >/dev/null 2>&1; then
    echo "required roles file must be a JSON array of strings: $required_roles_file" >&2
    exit 2
fi

overall_rc=0

while IFS= read -r username; do
    [ -z "$username" ] && continue

    echo "=== Processing user: ${username} ==="
    "$single_user_script" "$username" "$required_roles_file"
    rc=$?

    case "$rc" in
        0)
            ;;
        1)
            if [ "$overall_rc" -eq 0 ]; then
                overall_rc=1
            fi
            ;;
        2)
            overall_rc=2
            break
            ;;
        *)
            echo "Error: unexpected return code ${rc} from ${single_user_script}" >&2
            overall_rc=2
            break
            ;;
    esac
done < <(jq -r '.[]' "$users_file")

exit "$overall_rc"