#!/bin/bash


function archiva_get_managed_repository() {

    local repository="$1"

    curl --request GET \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --output output.json \
         ${archivaUrl}/${getManagedRepositoryEndpoint}/${repository} > stdout.txt
    local result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "exit code: ${result}"
        echo "Error: $0: archiva_get_managed_repository[${LINENO}]"
        echo "http code: ${result}"
        echo "---[ stdout.txt ]----------------------------------------------------------------"
        cat stdout.txt
        return 2
    fi
    
    status=$(cat stdout.txt)
    if [ ${status} -eq 200 ]; then
        :
    elif [ ${status} -eq 204 ]; then
        return 1
    else 
        echo "Error: $0: archiva_get_managed_repository[${LINENO}]: status: ${status}"
        jq . output.json
        return 2
    fi
}