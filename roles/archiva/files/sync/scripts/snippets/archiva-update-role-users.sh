#!/bin/bash

function archiva_update_role_users() {

    if [ -z "$1" ]; then
        echo "request data filename not specified"
        exit 2
    fi
    local datafile="$1"

    curl --request POST \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --data "@${datafile}" \
         --output output.json \
         ${archivaUrl}/${updateRoleUsersEndpoint} > stdout.txt
    local result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0: archiva_update_role_users[${LINENO}]: result: ${result}"
        return 2
    fi

    local status=$(cat stdout.txt)
    if [ ! ${status} -eq 200 ]; then
        echo "Error: $0: archiva_update_role_users[${LINENO}]: status: ${status}"
        return 2
    fi

    local output=$(cat output.json)
    if [ ${output} != "true" ]; then
        echo "Error: $0: archiva_update_role_users[${LINENO}]: output: ${output}"
        cat output.json
        return 2
    fi
}