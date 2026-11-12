#1/bin/bash

cd ~/projects/builder




#
# create the  namespace 'jenkins'
#
kubectl get namespace jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    echo "namepace 'jenkins' already exists"
elif [ ${result} -eq 1 ]; then
    kubectl create namespace jenkins
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        echo "error creating namespace: jenkins"
        exit 1
    fi
else
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error getting namespace 'jenkins'"
    exit 1
fi

#
# Make 'jenkins' the default namespace
#
doit=false
output=$(kubectl config view -o json | jq --raw-output '.contexts[].context.namespace')
result=$?
if [ ${result} -eq 0 ]; then
    if [ "${output}" = "jenkins" ]; then
        echo "the default namespace is already 'jenkins'"
    else
        doit=true
    fi
else
    doit=true
fi

if [ "$doit" = true ]; then
    echo "setting the default namespace to: jenkins"
    kubectl config set-context --current --namespace=jenkins 1>/dev/null 2>/dev/null
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}]: ${result}"
        exit 1
    fi
fi

echo "helm template the chart"
helm template -s templates/jenkins-service.yaml builder helm/builder
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error installing helm chart 'builder'"
    exit 1
fi

echo "Success!"
