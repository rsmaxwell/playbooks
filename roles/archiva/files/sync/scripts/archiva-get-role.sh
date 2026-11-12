#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-get-role.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *



archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi





rolename=$1
if [ -z "$1" ]; then
    echo "rolename not specified"
    exit 1
fi


archiva_get_role "${rolename}" role.json
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    echo "role '${rolename}' not found"
    exit 1
else
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi

jq . role.json
