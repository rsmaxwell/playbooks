#!/bin/bash

function archiva_convert_role() {

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


    local work="{}"

    local name=$(jq '.name' ${input_filename})
    local work=$(echo ${work} | jq --argjson foo "${name}" '. + { name: $foo }')

    local isNull=$(jq '.description | type == "null"' ${input_filename})
    if [ "${isNull}" == true ]; then
        description='""'
    else
        description==$(jq '.description' ${input_filename})
    fi
    work=$(echo ${work} | jq --argjson foo "${description}" '. + { description: $foo }')

    assignable=$(jq '.assignable' ${input_filename})
    work=$(echo ${work} | jq --argjson foo "${assignable}" '. + { assignable: $foo }')

    childRoleNames=$(jq '.childRoleNames' ${input_filename})
    work=$(echo ${work} | jq --argjson foo "${childRoleNames}" '. + { childRoleNames: $foo }')



    local perms="{}"
    for row in $(jq -r '.permissions[] | @base64' ${input_filename}); do
        _jq() {
         echo ${row} | base64 --decode | jq -r ${1}
        }

        perm=$(_jq '.')
        echo ${perm} | jq . > perm.json

        archiva_convert_permission perm.json perm2.json

        local perm2=$(cat perm2.json | jq .)

        perms=$(echo ${perms} | jq --argjson foo "${perm2}" '. |= [ $foo ]')
    done

    local parentRoleNames=$(jq '.parentRoleNames' output.json)
    work=$(echo ${work} | jq --argjson foo "${parentRoleNames}" '. + { parentRoleNames: $foo }')



    local otherUsers="[]"
    found=$(jq 'has("otherUsers")' ${input_filename})
    if [ "${found}" = true ]; then
        for row in $(jq -r '.otherUsers?[] | @base64' ${input_filename}); do
            _jq() {
             echo ${row} | base64 --decode | jq -r ${1}
            }
    
            user=$(_jq '.')
            echo ${user} | jq . > user.json
            archiva_convert_user user.json user2.json
            user2=$(cat user2.json | jq .)
            otherUsers=$(echo ${otherUsers} | jq --argjson foo "${user2}" '. |= [ $foo ]')
        done
    fi
    work=$(echo ${work} | jq --argjson foo "${otherUsers}" '. + { otherUsers: $foo }')



    local parentsRolesUsers="[]"
    found=$(jq 'has("parentsRolesUsers")' ${input_filename})
    if [ "${found}" = true ]; then
        for row in $(jq -r '.parentsRolesUsers[] | @base64' ${input_filename}); do
            _jq() {
             echo ${row} | base64 --decode | jq -r ${1}
            }
    
            user=$(_jq '.')
            echo ${user} | jq . > user.json
            archiva_convert_user user.json user2.json
            user2=$(cat user2.json | jq .)
            parentsRolesUsers=$(echo ${parentsRolesUsers} | jq --argjson foo "${user2}" '. |= [ $foo ]')
        done
        work=$(echo ${work} | jq --argjson foo "${parentsRolesUsers}" '. + { parentsRolesUsers: $foo }')
    fi



    local users="[]"
    found=$(jq 'has("users")' ${input_filename})
    if [ "${found}" = true ]; then
        for row in $(jq -r '.users[] | @base64' ${input_filename}); do
            _jq() {
             echo ${row} | base64 --decode | jq -r ${1}
            }
    
            user=$(_jq '.')
            echo ${user} | jq . > user.json
            archiva_convert_user user.json user2.json
            user2=$(cat user2.json | jq .)
            users=$(echo ${users} | jq --argjson foo "${user2}" '. |= [ $foo ]')
        done
        work=$(echo ${work} | jq --argjson foo "${users}" '. + { users: $foo }')
    fi



    local permissions="[]"
    found=$(jq 'has("users")' ${input_filename})
    if [ "${found}" = true ]; then
        for row in $(jq -r '.permissions[] | @base64' ${input_filename}); do
            _jq() {
             echo ${row} | base64 --decode | jq -r ${1}
            }
    
            permission=$(_jq '.')
            echo ${permission} | jq . > permission.json
            archiva_convert_permission permission.json permission2.json
            permission2=$(jq . permission2.json)
            permissions=$(echo ${permissions} | jq --argjson foo "${permission2}" '. + [ $foo ]')
        done
        work=$(echo ${work} | jq --argjson foo "${permissions}" '. + { permissions: $foo }')
    fi



    echo "${work}" | jq --sort-keys . > ${output_filename}
}
