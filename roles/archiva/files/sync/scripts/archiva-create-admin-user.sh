#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-create-admin-user.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *

archiva_create_admin_user
result=$?

if [ ${result} -eq 0 ]; then
    # API says admin user was created
    exit 1
elif [ ${result} -eq 1 ]; then
    # API says it was not created, normally because it already exists
    exit 0
else
    echo "Error: ..."
    exit 2
fi
