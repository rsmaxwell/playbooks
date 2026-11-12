#!/bin/bash

. ${SCRIPT_DIR}/snippets/urlencode.sh

function archiva_get_role() {

    if [ -z "$1" ]; then
        echo "role not specified"
        exit 2
    fi
    local rolename=$(urlencode "$1")

    local output_filename="output.json"


    curl --request GET \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --output "${output_filename}" \
         ${archivaUrl}/${getRoleEndpoint}/${rolename} > stdout.txt
    local result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "exit code: ${result}"
        echo "Error: $0: archiva_get_user[${LINENO}]"
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
        echo "Error: $0: archiva_get_user[${LINENO}]: status: ${status}"
        cat "${output_filename}"
        return 2
    fi

    cat ${output_filename}
}