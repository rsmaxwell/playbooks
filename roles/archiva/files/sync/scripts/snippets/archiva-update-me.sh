#!/bin/bash

function archiva_update_me() {

    echo $1 > request-body.json

    jq . request-body.json

    curl --request POST \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --data @request-body.json \
         --output output.json \
         ${archivaUrl}/${updateMeEndpoint} > stdout.txt
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0: archiva_create_user[${LINENO}]: result: ${result}"
        return 2
    fi

    status=$(cat stdout.txt)
    if [ ! ${status} -eq 200 ]; then
        echo "Error: $0: archiva_create_user[${LINENO}]: status: ${status}"
        return 2
    fi

    output=$(cat output.json)
    if [ ${output} != "true" ]; then
        echo "Error: $0: archiva_create_user[${LINENO}]: output: ${output}"
        return 2
    fi
}
