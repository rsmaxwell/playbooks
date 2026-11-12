#!/bin/bash
set -u



mkdir -p "${HOME}/temp"
cd "${HOME}/temp" || exit 2
rm -f test-upload.txt curl-response.txt

if [ -z "${1:-}" ]; then
    echo "username not specified" >&2
    exit 2
fi
test_username="$1"

if [ -z "${2:-}" ]; then
    echo "password not specified" >&2
    exit 2
fi
test_password="$2"

if [ -z "${3:-}" ]; then
    echo "repository not specified" >&2
    exit 2
fi
repository="$3"

if [ -z "${4:-}" ]; then
    echo "groupId not specified" >&2
    exit 2
fi
group_id="$4"

if [ -z "${5:-}" ]; then
    echo "artifactId not specified" >&2
    exit 2
fi
artifact_id="$5"

if [ -z "${6:-}" ]; then
    echo "version not specified" >&2
    exit 2
fi
version="$6"

group_path="${group_id//./\/}"
filename="${artifact_id}-${version}.txt"

cat > test-upload.txt <<EOF
Archiva permission test
user=${test_username}
repository=${repository}
groupId=${group_id}
artifactId=${artifact_id}
version=${version}
timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
EOF

upload_url="${archivaUrl}/${repository}/${group_path}/${artifact_id}/${version}/${filename}"

http_code="$(
  curl \
    --silent \
    --show-error \
    --write-out "%{http_code}" \
    --user "${test_username}:${test_password}" \
    --upload-file test-upload.txt \
    --output curl-response.txt \
    "${upload_url}"
)"
result=$?

if [ "$result" -ne 0 ]; then
    echo "Error: curl failed with exit code ${result}" >&2
    exit 2
fi

case "$http_code" in
    201|200)
        echo "Success: upload permitted"
        echo "Uploaded to: ${upload_url}"
        exit 0
        ;;
    401|403)
        echo "Denied: upload not permitted for this user/repository"
        echo "HTTP status: ${http_code}"
        cat curl-response.txt
        exit 1
        ;;
    409)
        echo "Denied: conflict: artifact already exists"
        echo "HTTP status: ${http_code}"
        cat curl-response.txt
        exit 1
        ;;
    *)
        echo "Error: unexpected HTTP status: ${http_code}" >&2
        cat curl-response.txt >&2
        exit 2
        ;;
esac