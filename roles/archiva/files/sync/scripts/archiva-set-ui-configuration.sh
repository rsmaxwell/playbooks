#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-set-ui-configuration.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *



archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva-get-ui-configuration[${LINENO}]: result=${result}"
    exit 1
fi






archiva_set_ui_configuration 
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva-get-ui-configuration[${LINENO}]: result=${result}"
    exit 1
fi

jq . output.json
