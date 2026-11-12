#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-get-ui-configuration.sh
. ${SCRIPT_DIR}/snippets/archiva-set-ui-configuration.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *


if [ -z "$1" ]; then
    echo "No argument supplied"
    exit 1
elif [ "$1" = true ]; then
    variable=true
elif [ "$1" = false ]; then
    variable=false
else
    echo "Unexpected value for boolean: '$1'"
    exit 1
fi



archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva-disable-registration[${LINENO}]: result=${result}"
    exit 1
fi




archiva_get_ui_configuration 
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva-disable-registration[${LINENO}]: result=${result}"
    exit 1
fi


ui_configuration=$(jq --argjson variable $variable '.disableRegistration = $variable' ui-configuration.json)
echo ${ui_configuration} > ui-configuration.json


jq . ui-configuration.json


archiva_set_ui_configuration 
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva-disable-registration[${LINENO}]: result=${result}"
    exit 1
fi


