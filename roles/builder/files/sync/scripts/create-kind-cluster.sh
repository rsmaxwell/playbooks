#!/bin/bash

cd ~/projects/builder

# 
# make sure the 'kind' cluster exists
#
found=false
output="$(docker ps | wc -l)"
if [ "${output}" -le 1 ]; then
    echo "no docker containers are running"
else
    output=$(kind get clusters)
    if [ "${output}" = "kind" ]; then
        echo "the 'kind' cluster already exists"
        found=true
    fi
fi

if [ "${found}" = false ]; then
    kind create cluster --config files/cluster.yaml
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}]"
        echo "'kind create cluster' failed"
        exit 2
    fi

    echo "changed"
    exit 1
fi

echo "ok"
