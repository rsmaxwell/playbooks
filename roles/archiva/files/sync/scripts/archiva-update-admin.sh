#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-update-me.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *

archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi





read -r -d '' userdata << EOF
{
  "username": "${admin_username}",
  "fullName": "${admin_fullname}",
  "email": "${admin_email}",
  "password": "",
  "previousPassword": "${admin_password}"
}
EOF

archiva_update_me "${userdata}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: result=${result}"
    jq . ~/temp/output.json
    exit 1
fi

jq . output.json


