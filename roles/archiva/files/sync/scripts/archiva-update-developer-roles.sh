#!/bin/bash
set -u

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

mkdir -p "${HOME}/temp"
cd "${HOME}/temp" || exit 2

users_file="developer-users.json"
roles_file="developer-required-roles.json"

cat > "$users_file" <<'EOF'
[
  "richard"
]
EOF

cat > "$roles_file" <<'EOF'
[
  "Registered User",
  "Global Repository Manager"
]
EOF

"${SCRIPT_DIR}/archiva-update-users-roles.sh" "$users_file" "$roles_file"
exit $?