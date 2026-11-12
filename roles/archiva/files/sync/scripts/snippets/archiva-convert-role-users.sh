#!/bin/bash

function archiva_convert_role_users() {

    if [ -z "${1:-}" ]; then
        echo "role input filename not specified" >&2
        return 1
    fi
    local role_filename="$1"

    if [ -z "${2:-}" ]; then
        echo "user input filename not specified" >&2
        return 1
    fi
    local user_filename="$2"

    if [ -z "${3:-}" ]; then
        echo "output filename not specified" >&2
        return 1
    fi
    local output_filename="$3"

    jq --slurpfile user "$user_filename" '
        if any((.users // [])[].username; . == $user[0].username) then
            .
        else
            .users = ((.users // []) + [$user[0]])
        end
    ' "$role_filename" | jq --sort-keys . > "$output_filename"
}