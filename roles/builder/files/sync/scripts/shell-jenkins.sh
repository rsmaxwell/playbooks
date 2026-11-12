#1/bin/bash

cd ~/projects/builder



podid=$(kubectl get pods --selector=app=jenkins -o json | jq --raw-output '.items[].metadata.name')
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error getting pod id"
    exit 1
fi




kubectl exec ${podid} -it -- bash
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error getting pod id"
    exit 1
fi
