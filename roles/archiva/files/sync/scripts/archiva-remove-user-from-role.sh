#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-get-role.sh
. ${SCRIPT_DIR}/snippets/archiva-update-role-users.sh
. ${SCRIPT_DIR}/snippets/archiva-convert-role.sh
. ${SCRIPT_DIR}/snippets/archiva-convert-user.sh
. ${SCRIPT_DIR}/snippets/archiva-convert-permission.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *


archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi

if [ -z "$1" ]; then
    echo "username not specified"
    exit 1
fi
username=$1

if [ -z "$2" ]; then
    echo "rolename not specified"
    exit 1
fi
rolename=$2





archiva_get_role "${rolename}" role.json
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    echo "role '${rolename}' not found"
    exit 1
else
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi


archiva_convert_role role.json role2.json

# Check the user is in the 'users' array
userdata=$(jq -r ".users[] | select(.username == \"${username}\")" role2.json)
if [ -z "${userdata}" ]; then
  echo "user '${username}' not found in role.users" 
  exit 1
fi



# Remove the user from the 'users' array
request=$(jq -r --arg foo ${username} 'del(.users[] | select(.username == $foo))' role2.json)


# Add the user to both the 'otherUsers' and 'removedUsers' arrays
request=$(echo ${request} | jq --argjson foo "${userdata}" '.otherUsers += [$foo]')
request=$(echo ${request} | jq --argjson foo "${userdata}" '.removedUsers += [$foo]')

request=$(echo ${request} | jq --argjson foo true '. + { usersModified: $foo }')
request=$(echo ${request} | jq --argjson foo true '. + { modified: $foo }')



echo "${request}" | jq --sort-keys . > request.json
archiva_update_role_users request.json
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: result=${result}"
    exit 2
fi

echo "Success"

