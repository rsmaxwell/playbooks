#!/bin/bash

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

. ${SCRIPT_DIR}/snippets/archiva-login.sh
. ${SCRIPT_DIR}/snippets/archiva-add-managed-repository.sh

workdir="$(mktemp -d -t archiva-setup-XXXXXX)"
cd "$workdir"
rm -rf *



archiva_login "${admin_username}" "${admin_password}"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0: archiva_get_user[${LINENO}]: result=${result}"
    exit 1
fi





read -r -d '' repositorydata << EOF
{
  "id": "snapshots",
  "name": "Maven snapshots",
  "layout": "default",
  "indexDirectory": "/archiva-data/repositories/snapshots/.indexer",
  "description": "",
  "location": "/archiva-data/repositories/snapshots",
  
  "snapshots": true,
  "releases": false,
  
  "blockRedeployments": false,
  
  "scanned": true,
  "cronExpression": "0 0 * * * ?",
  
  "daysOlder": 30,
  "retentionCount": 5,
  "deleteReleasedSnapshots": true,

  "stageRepoNeeded": false,
  "stagingRepository": null,
  
  "resetStats": false,
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





read -r -d '' repositorydata << EOF
{
  "id": "integration",
  "name": "integration",
  "layout": "default",
  "indexDirectory": "/archiva-data/repositories/integration/.indexer",
  "description": "",
  "location": "/archiva-data/repositories/integration",
  
  "snapshots": false,
  "releases": true,
  
  "blockRedeployments": true,
  
  "scanned": true,
  "cronExpression": "0 0 * * * ?",

  "daysOlder": 0,
  "retentionCount": 0,
  "deleteReleasedSnapshots": false,
  
  "stageRepoNeeded": false,  
  "stagingRepository": null,
  
  "resetStats": false,
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





read -r -d '' repositorydata << EOF
{
  "id": "releases",
  "name": "releases",
  "layout": "default",
  "indexDirectory": "/archiva-data/repositories/releases/.indexer",
  "description": "",
  "location": "/archiva-data/repositories/releases",
  
  "snapshots": false,
  "releases": true,
  
  "blockRedeployments": true,
  
  "scanned": true,
  "cronExpression": "0 0 * * * ?",

  
  "daysOlder": 0,
  "retentionCount": 0,
  "deleteReleasedSnapshots": false,
  
  "stageRepoNeeded": false,  
  "stagingRepository": null,
  
  "resetStats": false,
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