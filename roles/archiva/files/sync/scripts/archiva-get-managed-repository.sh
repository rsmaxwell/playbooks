#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/rchiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-get-managed-repository.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *

archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi



repository=$1
if [ -z "$1" ]; then
    echo "repository not specified"
    exit 1
fi

archiva_get_managed_repository "${repository}"
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    echo "repository not found"
else
    echo "Error: $0[${LINENO}]: result=${result}"
    exit 1
fi


jq . output.json

