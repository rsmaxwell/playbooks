#!/bin/bash

. ${SCRIPT_DIR}/snippets/archiva-credentials.sh
. ${SCRIPT_DIR}/snippets/archiva-rest-api.sh

function archiva_create_admin_user() {

    cat << EOF > request-body.json
{
  "username": "${admin_username}",
  "password": "${admin_password}",
  "email": "${archiva_admin_email}",
  "fullName": "Administrator",
  "locked": false,
  "passwordChangeRequired": false,
  "permanent": false,
  "readOnly": false,
  "validated": true
}
EOF

    set -x

    curl --request POST \
         --silent \
         --write-out "%{http_code}" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --data @request-body.json \
         --output output.json \
         ${archivaUrl}/${createAdminUserEndpoint} > stdout.txt
    result=$?
    set +x
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0: archiva_create_admin_user[${LINENO}]: result: ${result}"
        cat stdout.txt; echo
        return 2
    fi

    status=$(cat stdout.txt)
    if [ ! ${status} -eq 200 ]; then
        echo "Error: $0: archiva_create_admin_user[${LINENO}]: status: ${status}"
        return 2
    fi

    output=$(cat output.json)
    if [ ${output} == "true" ]; then
        :
    elif [ ${output} == "false" ]; then
        echo "admin_user NOT created"
        return 1
    else
        echo "Error: $0: archiva_create_admin_user[${LINENO}]: output: ${output}"
        return 2
    fi
}
