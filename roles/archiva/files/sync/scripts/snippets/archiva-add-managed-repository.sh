#!/bin/bash

function archiva_add_managed_repository() {
    local request_body="$1"

    # Write JSON payload to a temp file (handles multi-line safely)
    local payload_file
    payload_file="$(mktemp -t archiva-managed-repo-XXXXXX.json)"
    printf '%s' "$request_body" > "$payload_file"

    curl --request POST \
         --silent \
         --write-out "%{http_code}\n" \
         --header "Content-Type: application/json" \
         --header "Accept: application/json" \
         --header "Origin: ${archivaUrl}" \
         --header "X-XSRF-TOKEN: ${validationToken}" \
         --cookie cookie.txt --cookie-jar cookie.txt \
         --data-binary @"$payload_file" \
         --output output.json \
         "${archivaUrl}/${addManagedRepositoryEndpoint}" > stdout.txt
    local result=$?

    rm -f "$payload_file"

    if [ "$result" -ne 0 ]; then
        echo "Error: $0: archiva_add_managed_repository[${LINENO}]: curl result: ${result}"
        return 2
    fi

    local status
    status="$(cat stdout.txt)"

    if [ "$status" -ne 200 ]; then
        echo "Error: $0: archiva_add_managed_repository[${LINENO}]: status: ${status}"
        jq . output.json
        return 2
    fi

    return 0
}
