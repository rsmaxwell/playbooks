#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-get-user.sh
. ${SCRIPT_DIR}/snippets/archiva-create-user.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *

archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi



archiva_get_user "${username}"
result=$?
if [ ${result} = 0 ]; then
    echo "User '${username}' already exists"
    exit 0
elif [ ${result} = 1 ]; then
    echo "User '${username}' does not exist"
else
    echo "Error: $0[${LINENO}]: result=${result}"
    exit 1
fi




read -r -d '' userdata << EOF
{
  "username": "${username}",
  "fullName": "${fullname}",
  "email": "${email}",
  "password": "${password}",
  "passwordChangeRequired": false,
  "validated": true
}
EOF

archiva_create_user "${userdata}"
result=$?
if [ ${result} = 0 ]; then
    echo "User '${username}' already exists"
    exit 0
elif [ ${result} = 1 ]; then
    echo "User '${username}' does not exist"
else
    exit 2
fi
