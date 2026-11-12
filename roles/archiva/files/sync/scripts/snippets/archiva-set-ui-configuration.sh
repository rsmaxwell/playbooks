#!/bin/bash


function archiva_set_ui_configuration() {

    curl --request POST \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --data @ui-configuration.json \
         --output output.json \
         ${archivaUrl}/${setUiConfigurationEndpoint} > stdout.txt
    local result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "exit code: ${result}"
        echo "Error: $0: archiva_get_ui_configuration[${LINENO}]"
        echo "http code: ${result}"
        echo "---[ stdout.txt ]----------------------------------------------------------------"
        cat stdout.txt; echo
        return 2
    fi
    
    status=$(cat stdout.txt)
    if [ ${status} -eq 200 ]; then
        :
    elif [ ${status} -eq 204 ]; then
        :
    else 
        echo "Error: $0: archiva_get_ui_configuration[${LINENO}]: status: ${status}"
        jq . output.json
        return 2
    fi
}