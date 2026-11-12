#!/bin/sh

echo "delete the default cluster 'kind'"
kind delete cluster
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}]"
    echo "'kind delete cluster' failed"
    exit 2
fi
