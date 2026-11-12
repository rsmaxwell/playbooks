#!/bin/bash

echo "check the project directory exists"
builder_project_dir_exists=false
if [ -d ~/git/github.com/rsmaxwell/generate ]; then
    builder_project_dir_exists=true
else
    echo "make the parent project directory"
    mkdir -p ~/git/github.com/rsmaxwell
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        exit 2
    fi
    
    echo "change to the parent project directory"
    cd ~/git/github.com/rsmaxwell
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        exit 2
    fi
    
    echo "clone the project"
    git clone https://github.com/rsmaxwell/generate.git
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        exit 2
    fi
fi

echo "change to the project directory"
cd ~/git/github.com/rsmaxwell/generate
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}] result: ${result}"
    exit 2
fi

echo "get the current commit hash"
original_commit_hash=$(git rev-parse HEAD)
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}] result: ${result}"
    exit 2
fi

echo "make sure the project is uptodate"
git pull
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}] result: ${result}"
    exit 2
fi

echo "get the current commit hash"
current_commit_hash=$(git rev-parse HEAD)
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}] result: ${result}"
    exit 2
fi

echo "original_commit_hash: ${original_commit_hash}"
echo "current_commit_hash:  ${current_commit_hash}"

if [ "${current_commit_hash}" = "${original_commit_hash}" ]; then
    echo "already uptodate"
    exit 0
fi

echo "changed"
exit 1
