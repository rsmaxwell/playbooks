#!/bin/bash

function archiva_get_effectively_assigned_roles() {

    local username="$1"

    curl --request GET \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --output output.json \
         ${archivaUrl}/${getEffectivelyAssignedRolesEndpoint}/${username} > stdout.txt
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}]: result: ${result}"
        return 2
    fi

    status=$(cat stdout.txt)
    if [ ${status} -eq 200 ]; then
        :
    else 
        echo "Error: $0: archiva_get_effectivly_assigned_roles[${LINENO}]: status: ${status}"
        jq . output.json
        return 2
    fi
}
