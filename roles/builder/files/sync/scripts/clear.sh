#1/bin/bash

cd ~/projects/builder



podid=$(kubectl get pods --selector=job-name=jenkins-waiter -o json | jq --raw-output '.items[].metadata.name')
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error getting pod id"
    exit 1
fi




kubectl exec ${podid} -- bash -c "rm -rf /var/jenkins_home/*"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error getting pod id"
    exit 1
fi




kubectl exec ${podid} -- bash -c "rm -rf /var/jenkins_home/.*"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error getting pod id"
    exit 1
fi




echo "Success!"






