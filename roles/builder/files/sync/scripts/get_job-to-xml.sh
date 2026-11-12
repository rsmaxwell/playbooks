#!/bin/bash


echo "check the tool exists"
tool_commit=junk
tool_is_installed=false
if [ -f ~/go/bin/job-to-xml ]; then
    tool_is_installed=true
    tool_commit=$(~/go/bin/job-to-xml -version | grep "GitCommit:*" | cut -d ' ' -f 1 --complement)
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        exit 2
    fi
    echo "tool_commit: ${tool_commit}"
fi

echo "check the project directory exists"
builder_project_dir_exists=false
if [ -d ~/go/src/github.com/rsmaxwell/job-to-xml ]; then
    builder_project_dir_exists=true
else
    echo "make the parent project directory"
    mkdir -p ~/go/src/github.com/rsmaxwell
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        exit 2
    fi
    
    echo "change to the parent project directory"
    cd ~/go/src/github.com/rsmaxwell
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        exit 2
    fi
    
    echo "clone the project"
    git clone https://github.com/rsmaxwell/job-to-xml.git
    result=$?
    if [ ! ${result} -eq 0 ]; then
        echo "Error: $0[${LINENO}] result: ${result}"
        exit 2
    fi
fi

echo "change to the project directory"
cd ~/go/src/github.com/rsmaxwell/job-to-xml
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
git_commit=$(git rev-parse HEAD)
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}] result: ${result}"
    exit 2
fi

echo "git_commit: ${git_commit}"

if [ "${git_commit}" = "${tool_commit}" ]; then
    echo "already uptodate"
    exit 0
fi

echo "out-of-date, so need to rebuild"

export BUILD_ID="(none)"
export GIT_COMMIT=${git_commit}
export GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
export GIT_URL=$(git config --get remote.origin.url)

echo "BUILD_ID:   $BUILD_ID"
echo "GIT_COMMIT: $GIT_COMMIT"
echo "GIT_BRANCH: $GIT_BRANCH"
echo "GIT_URL:    $GIT_URL"

echo "generate resources and source code"
go generate ./...
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}] result: ${result}"
    exit 2
fi

echo "build and install the tool"
go install ./...
result=$?
if [ ! ${result} -eq 0 ]; then
    echo "Error: $0[${LINENO}] result: ${result}"
    exit 2
fi

echo "changed"
exit 1
