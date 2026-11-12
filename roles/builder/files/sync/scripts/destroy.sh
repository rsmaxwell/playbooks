#1/bin/bash

ok=true

cd ~/projects/builder


# 
# make sure the 'kind' cluster exists
#
found=false
output="$(docker ps | wc -l)"
if [ "${output}" -le 1 ]; then
    echo "no docker containers are running"
    exit 0
else
    output=$(kind get clusters)
    if [ ! "${output}" = "kind" ]; then
        echo "no 'kind' cluster could be found"
        exit 0
    fi
fi


echo "uninstalling chart: 'builder'"
helm uninstall builder 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error uninstalling chart"
    ok=false
fi





echo "deleting the chart: 'builder'"
helm delete builder jenkins --namespace=jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error deleting the chart"
    ok=false
fi






echo "deleting the deployment 'gradle'"
helm delete deployment gradle --namespace=jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error deleting the deployment 'gradle'"
    ok=false
fi

echo "deleting the deployment 'gradle-helper'"
helm delete deployment -helper --namespace=jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error deleting the deployment 'gradle-helper'"
    ok=false
fi

echo "deleting the deployment 'bash-helper'"
helm delete deployment bash-helper --namespace=jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error deleting the deployment 'bash-helper'"
    ok=false
fi

echo "deleting the deployment 'maven-helper'"
helm delete deployment maven-helper --namespace=jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error deleting the deployment 'maven-helper'"
    ok=false
fi

echo "deleting the deployment 'jenkins-helper'"
helm delete deployment jenkins-helper --namespace=jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error deleting the deployment 'jenkins-helper'"
    ok=false
fi

echo "deleting the deployment 'jenkins'"
helm delete deployment jenkins --namespace=jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    :
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}] result: ${result}"
    echo "error deleting the deployment 'jenkins'"
    ok=false
fi



#
# Clear the default namespace
#
doit=false
output=$(kubectl config view -o json | jq --raw-output '.contexts[].context.namespace')
result=$?
if [ ${result} -eq 0 ]; then
    if [ "${output}" = "default" ]; then
        :
    else
        doit=true
    fi
else
    doit=true
fi

if [ "$doit" = true ]; then
    echo "setting the default namespace to: default"
    kubectl config set-context --current --namespace=default 1>/dev/null 2>/dev/null
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}]: ${result}"
        ok=false
    fi
fi

kubectl get namespace jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    echo "deleting namespace 'jenkins'"
    kubectl delete namespace jenkins
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        echo "error deleting namespace: jenkins"
        ok=false
    fi
elif [ ${result} -eq 1 ]; then
    :
else
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error getting namespace: jenkins"
    ok=false
fi










# echo "deleting the persistentvolume 'jenkins-pv'"
# kubectl delete persistentvolume jenkins-pv 1>/dev/null 2>/dev/null
# result=$?
# if [ ${result} -eq 0 ]; then
#     :
# elif [ ${result} -eq 1 ]; then
#     :
# else
#     echo "Error: $0[${LINENO}] result: ${result}"
#     echo "error deleting the persistentvolume 'jenkins-pv'"
#     ok=false
# fi
# 
# echo "deleting the persistentvolume 'maven-pv'"
# kubectl delete persistentvolume maven-pv 1>/dev/null 2>/dev/null
# result=$?
# if [ ${result} -eq 0 ]; then
#     :
# elif [ ${result} -eq 1 ]; then
#     :
# else
#     echo "Error: $0[${LINENO}] result: ${result}"
#     echo "error deleting the persistentvolume 'maven-pv'"
#     ok=false
# fi
# 
# echo "deleting the persistentvolume 'gradle-pv'"
# kubectl delete persistentvolume gradle-pv 1>/dev/null 2>/dev/null
# result=$?
# if [ ${result} -eq 0 ]; then
#     :
# elif [ ${result} -eq 1 ]; then
#     :
# else
#     echo "Error: $0[${LINENO}] result: ${result}"
#     echo "error deleting the persistentvolume 'gradle-pv'"
#     ok=false
# fi
# 
# echo "deleting the persistentvolume 'golang-pv'"
# kubectl delete persistentvolume golang-pv 1>/dev/null 2>/dev/null
# result=$?
# if [ ${result} -eq 0 ]; then
#     :
# elif [ ${result} -eq 1 ]; then
#     :
# else
#     echo "Error: $0[${LINENO}] result: ${result}"
#     echo "error deleting the persistentvolume 'golang-pv'"
#     ok=false
# fi
# 
# echo "deleting the persistentvolume 'golang-alpine-pv'"
# kubectl delete persistentvolume golang-alpine-pv 1>/dev/null 2>/dev/null
# result=$?
# if [ ${result} -eq 0 ]; then
#     :
# elif [ ${result} -eq 1 ]; then
#     :
# else
#     echo "Error: $0[${LINENO}] result: ${result}"
#     echo "error deleting the persistentvolume 'golang-alpine-pv'"
#     ok=false
# fi
# 
# echo "deleting the storageclass 'local-storage'"
# kubectl delete storageclass local-storage 1>/dev/null 2>/dev/null
# result=$?
# if [ ${result} -eq 0 ]; then
#     :
# elif [ ${result} -eq 1 ]; then
#     :
# else
#     echo "Error: $0[${LINENO}] result: ${result}"
#     echo "error deleting the storageclass 'local-storage'"
#     ok=false
# fi








echo "wait for the pvc 'jenkins-pvc'to be deleted"
kubectl wait --for=delete pvc jenkins-pvc
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    ok=false
fi

echo "wait for the pvc 'maven-pvc' to be deleted"
kubectl wait --for=delete pvc maven-pvc
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    ok=false
fi

echo "wait for the pvc 'gradle-pvc' to be deleted"
kubectl wait --for=delete pvc gradle-pvc
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    ok=false
fi

echo "wait for the pvc 'golang-pvc' to be deleted"
kubectl wait --for=delete pvc golang-pvc
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    ok=false
fi

echo "wait for the pvc 'golang-alpine-pvc' to be deleted"
kubectl wait --for=delete pvc golang-alpine-pvc
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    ok=false
fi




if [ ${ok} = false ]; then
    exit 2
fi

echo "Success!"

