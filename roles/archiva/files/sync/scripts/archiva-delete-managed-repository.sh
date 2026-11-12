#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-delete-managed-repository.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *

archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 2
fi


repository=$1
if [ -z "$1" ]; then
    echo "repository not specified"
    exit 2
fi



archiva_delete_managed_repository "${repository}"
result=$?
if [ ${result} -eq 0 ]; then
    : 
elif [ ${result} -eq 1 ]; then
    echo "repository not found"
    exit 1
else
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 2
fi

echo "Success"
