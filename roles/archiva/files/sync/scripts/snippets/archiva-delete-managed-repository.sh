#!/bin/bash

function archiva_delete_managed_repository() {

    local repositoryId="$1"

    curl --request GET \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --output output.json \
         ${archivaUrl}/${deleteManagedRepositoryEndpoint}?repositoryId=${repositoryId} > stdout.txt
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0: archiva_delete_managed_repository[${LINENO}]: result: ${result}"
        return 2
    fi

    status=$(cat stdout.txt)
    if [ ${status} -eq 200 ]; then
        :
    elif [ ${status} -eq 500 ]; then
        return 1
    else
        echo "Error: $0: archiva_delete_managed_repository[${LINENO}]: status: ${status}"
        return 2
    fi

    output=$(cat output.json)
    if [ ${output} != "true" ]; then
        echo "Error: $0: archiva_delete_managed_repository[${LINENO}]: output: ${output}"
        return 2
    fi
}
