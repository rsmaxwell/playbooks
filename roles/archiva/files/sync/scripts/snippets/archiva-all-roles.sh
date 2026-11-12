#!/bin/bash

function archiva_all_roles() {

    set -x
    curl --request GET \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --output output.json \
         ${archivaUrl}/${allRolesEndpoint} > stdout.txt
    result=$?
    set +x
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0: archiva_all_roles[${LINENO}]: result: ${result}"
        cat stdout.txt
		echo ""
        exit 1
    fi

    status=$(cat stdout.txt)
    if [ ! ${status} -eq 200 ]; then
        echo "Error: $0: archiva_all_roles[${LINENO}]: status: ${status}"
        exit 1
    fi
}
