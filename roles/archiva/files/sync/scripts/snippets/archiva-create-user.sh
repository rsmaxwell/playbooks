#!/bin/bash

function archiva_create_user() {

    local retcode=0

    echo $1 > request-body.json

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
         ${archivaUrl}/${createUserEndpoint} > stdout.txt
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0: archiva_create_user[${LINENO}]: result: ${result}"
        if (( ${retcode} < 2 )); then
            retcode=2
        fi
    fi

    status=$(cat stdout.txt)
    if [ ! ${status} -eq 200 ]; then
        echo "Error: $0: archiva_create_user[${LINENO}]: status: ${status}"
        if (( ${retcode} < 2 )); then
            retcode=2
        fi
    fi

    output=$(cat output.json)
    if [ "${output}" != "true" ]; then
        echo "Error: $0: archiva_create_user[${LINENO}]: output: ${output}"
        if (( ${retcode} < 2 )); then
            retcode=2
        fi
    fi

    return ${retcode}
}
