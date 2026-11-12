#!/bin/bash

function archiva_convert_permission() {

    if [ -z "$1" ]; then
        echo "input filename not specified"
        exit 1
    fi
    local input_filename=$1

    if [ -z "$2" ]; then
        echo "output filename not specified"
        exit 1
    fi
    local output_filename=$2


    local original_name=$(jq '.name' ${input_filename})

    local original_operation=$(jq '.operation' ${input_filename})
    local original_operation_name=$(jq '.operation.name' ${input_filename})

    local original_resource=$(jq '.resource' ${input_filename})
    local original_resource_identifier=$(jq '.resource.identifier' ${input_filename})
    local original_resource_pattern=$(jq '.resource.pattern' ${input_filename})


    local perm="{}"

    local original_name=$(_jq '.name')
    perm=$(echo ${perm} | jq --arg foo "${original_name}" '. + { name: $foo }')

    local operation="{}"
    operation=$(echo ${operation} | jq --argjson foo "${original_operation_name}" '. + { name: $foo }')
    perm=$(echo ${perm} | jq --argjson foo "${operation}" '. + { operation: $foo }')

    local resource="{}"
    resource=$(echo ${resource} | jq --argjson foo "${original_resource_identifier}" '. + { identifier: $foo }')
    resource=$(echo ${resource} | jq --argjson foo "${original_resource_pattern}" '. + { pattern: $foo }')
    perm=$(echo ${perm} | jq --argjson foo "${resource}" '. + { resource: $foo }')

    echo ${perm} | jq --sort-keys . > ${output_filename}
}