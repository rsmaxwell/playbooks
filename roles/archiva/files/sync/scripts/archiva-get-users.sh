#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-credentials.sh
. ${SCRIPT_DIR}/snippets/archiva-rest-api.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *

###############################################################################
# Login as 'admin'
###############################################################################

cat << EOF > request-body.json
{
  "username": "${admin_username}",
  "password": "${admin_password}"
}
EOF

echo "---[ request-body.json ]---------------------------------------------------------"
jq . request-body.json
echo "---------------------------------------------------------------------------------"

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
     ${archivaUrl}/${loginEndpoint} > stdout.txt
result=$?
set +x
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]"
    cat stdout.txt
    echo ""
    exit 1
fi

# echo "Success"
# echo "---[ output.json ]----------------------------------------------------------------"
# jq . output.json
# echo ""
# echo "---[ cookie.txt ]----------------------------------------------------------------"
# cat cookie.txt
# echo ""
# echo "---[ stdout.txt ]----------------------------------------------------------------"
# cat stdout.txt
# echo ""
# echo "---------------------------------------------------------------------------------"

status=$(cat stdout.txt)
if [ ! ${status} -eq 200 ]; then
    echo "Error: $0[${LINENO}]: Unexpected HTTP status: ${status}"
    cat output.json
    exit 1
fi

validationToken="$(jq '.validationToken' output.json)"
#echo "validationToken: ${validationToken}"


###############################################################################
# get users
###############################################################################

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
     ${archivaUrl}/${getUsersEndpoint}
result=$?
set +x
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]"
    exit 1
fi

echo "Success"
echo "---[ output.json ]----------------------------------------------------------------"
jq . output.json
echo ""
echo "---------------------------------------------------------------------------------"
