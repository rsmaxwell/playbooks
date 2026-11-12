#!/bin/bash
set -u

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

mkdir -p "${HOME}/temp"
cd "${HOME}/temp" || exit 2

users_file="guest-users.json"
roles_file="guest-required-roles.json"

cat > "$users_file" <<'EOF'
[
  "guest"
]
EOF

cat > "$roles_file" <<'EOF'
[
    "Guest",
    "Global Repository Observer"
]
EOF

"${SCRIPT_DIR}/archiva-update-users-roles.sh" "$users_file" "$roles_file"
exit $?