#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-add-managed-repository.sh

mkdir -p ~/temp
cd ~/temp
rm -rf *



archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi





read -r -d '' repositorydata << EOF
{
  "id": "test",
  "name": "test",
  "layout": "default",
  "indexDirectory": "/archiva-data/repositories/test/.indexer",
  "description": "",
  "location": "/archiva-data/repositories/test",
  "snapshots": false,
  "releases": true,
  "blockRedeployments": true,
  "cronExpression": "0 0 * * * ?",
  "stagingRepository": null,
  "scanned": true,
  "daysOlder": 30,
  "retentionCount": 2,
  "deleteReleasedSnapshots": false,
  "stageRepoNeeded": false,
  "resetStats": false,
  "indexDirectory": false,
  "skipPackedIndexCreation": false
}
EOF

archiva_add_managed_repository "${repositorydata}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: result=${result}"
    exit 1
fi

jq . output.json
