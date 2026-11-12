#!/bin/bash

 
cd ~/projects/builder

echo "make sure the 'kind' cluster exists"
found=false
output="$(docker ps | wc -l)"
if [ "${output}" -le 1 ]; then
    echo "no docker containers are running"
else
    output=$(kind get clusters)
    if [ "${output}" = "kind" ]; then
        found=true
    fi
fi

if [ "${found}" = false ]; then
    echo "creating the 'kind' cluster"
    kind create cluster --config files/cluster.yaml
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}]"
        echo "'kind create cluster' failed"
        exit 1
    fi
fi

echo "make sure the namespace 'jenkins' exists"
kubectl get namespace jenkins 1>/dev/null 2>/dev/null
result=$?
if [ ${result} -eq 0 ]; then
    echo "the namespace 'jenkins' already exists"
elif [ ${result} -eq 1 ]; then
    echo "creating the namespace 'jenkins'"
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

echo "make sure the default namespace is 'jenkins'"
doit=false
output=$(kubectl config view -o json | jq --raw-output '.contexts[].context.namespace')
result=$?
if [ ${result} -eq 0 ]; then
    if [ "${output}" = "jenkins" ]; then
        :
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






echo "helm install the chart"
helm install \
  --set replicas.gradle_helper=1 \
  --set replicas.maven_helper=1 \
  --set replicas.bash=1 \
  --set replicas.helper=0 \
  --set replicas.jenkins=0 \
  builder helm/builder
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    echo "error installing helm chart 'builder'"
    exit 1
fi








echo "wait for the bash-helper deployment" 
kubectl wait deployment bash-helper --for condition=Available=True --timeout=5m
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "wait till 'bash-helper' is ready" 
kubectl wait --for=condition=ready pod --selector=app=bash-helper --timeout=5m
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "stop 'bash-helper'"
output=$(kubectl scale --replicas=0 deployment bash-helper )
result=$?
if [ ${result} -ne 0 ]; then
    echo "Error: $0[${LINENO}]"
    echo "${output}"
    exit 2    
fi






echo "start the jenkins-helper deployment" 
kubectl scale --replicas=1 deployment/jenkins-helper
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "wait till 'jenkins-helper' is ready" 
kubectl wait --for=condition=ready pod --selector=app=jenkins-helper --timeout=8m
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "get the id of the 'jenkins-helper' pod" 
podid=$(kubectl get pods --selector=app=jenkins-helper -o json | jq --raw-output '.items[].metadata.name')
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "copy the 'CASC' (i.e. configuration as code) file to 'jenkins-home'" 
kubectl cp files/jenkins.yaml ${podid}:/var/jenkins_home/
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "stop 'jenkins-helper'"
output=$(kubectl scale --replicas=0 deployment jenkins-helper )
result=$?
if [ ${result} -ne 0 ]; then
    echo "Error: $0[${LINENO}]"
    echo "${output}"
    exit 2    
fi





echo "wait till 'gradle-helper' is ready" 
kubectl wait --for=condition=ready pod --selector=app=gradle-helper --timeout=5m
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "get the id of the 'gradle-helper' pod" 
podid=$(kubectl get pods --selector=app=gradle-helper --output=jsonpath="{.items[].metadata.name}")
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "copy 'setup-gradle-home.sh' to the pod" 
kubectl cp files/setup-gradle-home.sh ${podid}:/root/
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "setup the '/home/gradle' directory" 
kubectl exec -it ${podid} -- bash -c "/root/setup-gradle-home.sh"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "copy 'gradle.properties' file to the pod" 
kubectl cp files/gradle.properties ${podid}:/home/gradle/.gradle/
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "set owner for the 'gradle.properties' file" 
kubectl exec -it ${podid} -- bash -c "chown 1000:1000 /home/gradle/.gradle/gradle.properties"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "set permissions for the 'gradle.properties' file" 
kubectl exec -it ${podid} -- bash -c "chmod 600 /home/gradle/.gradle/gradle.properties"
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "stop 'gradle-helper'"
output=$(kubectl scale --replicas=0 deployment gradle-helper )
result=$?
if [ ${result} -ne 0 ]; then
    echo "Error: $0[${LINENO}]"
    echo "${output}"
    exit 2    
fi





echo "wait till 'maven-helper' is ready" 
kubectl wait --for=condition=ready pod --selector=app=maven-helper --timeout=5m
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "get the id of the 'maven-helper' pod" 
podid=$(kubectl get pods --selector=app=maven-helper --output=jsonpath="{.items[].metadata.name}")
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "copy 'settings.xml' to the pod" 
kubectl cp files/settings.xml ${podid}:/root/.m2/
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "copy 'maven-repository-info' to the pod" 
kubectl cp files/maven-repository-info ${podid}:/root/.m2/
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "stop 'maven-helper'"
output=$(kubectl scale --replicas=0 deployment maven-helper )
result=$?
if [ ${result} -ne 0 ]; then
    echo "Error: $0[${LINENO}]"
    echo "${output}"
    exit 2    
fi








echo "start the jenkins deployment" 
kubectl scale --replicas=1 deployment/jenkins
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "wait for the jenkins deployment to be ready" 
kubectl wait deployment jenkins --for condition=Available=True --timeout=10m
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "wait till the 'jenkins' pod is ready" 
kubectl wait --for=condition=ready pod -l app=jenkins --timeout=5m
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi


echo "get the name of the 'jenkins' pod" 
podid=$(kubectl get pods --selector=app=jenkins -o json | jq --raw-output '.items[].metadata.name')
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "cleanup" 
kubectl exec ${podid} -- bash -c 'rm -rf /var/jenkins_home/plugins.txt /var/jenkins_home/jenkins.yaml'
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi




echo "create jobs" 
./scripts/create-jobs.sh
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]: ${result}"
    exit 1
fi

echo "Success!"

