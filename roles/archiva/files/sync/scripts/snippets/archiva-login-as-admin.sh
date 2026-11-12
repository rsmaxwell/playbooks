#!/bin/bash

. ${SCRIPT_DIR}/snippets/archiva-credentials.sh
. ${SCRIPT_DIR}/snippets/archiva-rest-api.sh


function login_as_admin() {

    mkdir -p ~/temp
    cd ~/temp
    rm -rf *

    curl --request POST \
         --silent \
         --write-out "%{http_code}" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --data @request-body.json \
         --output output.json \
         ${archivaUrl}/${loginEndpoint} > stdout.txt
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}]: result: ${result}"
        exit 1
    fi
    
    status=$(cat stdout.txt)
    if [ ! ${status} -eq 200 ]; then
        echo "Error: $0[${LINENO}]: status: ${status}"
        exit 1
    fi
    
    validationToken=$(jq -r '.validationToken' output.json)
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}]: result: ${result}"
        exit 1
    fi
}


