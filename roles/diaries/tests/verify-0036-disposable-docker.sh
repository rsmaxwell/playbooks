#!/usr/bin/env bash
# 0036 isolated Docker-side rsync verification. No production volumes/container actions.
set -euo pipefail
image="${1:-postgres:18-alpine}"
tmp="$(mktemp -d -t 0036-docker-rehearsal-XXXXXX)"
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/nas/.image-staging" "$tmp/previous/files" "$tmp/candidate/files"
printf 'unchanged\n' > "$tmp/nas/keep.txt"
printf 'updated\n' > "$tmp/nas/change.txt"
printf 'new\n' > "$tmp/nas/add.txt"
printf 'excluded\n' > "$tmp/nas/.image-staging/inflight"
cp -p "$tmp/nas/keep.txt" "$tmp/previous/files/keep.txt"
printf 'old\n' > "$tmp/previous/files/change.txt"
printf 'obsolete\n' > "$tmp/previous/files/delete.txt"
chmod 755 "$tmp" "$tmp/nas" "$tmp/previous" "$tmp/previous/files" "$tmp/candidate" "$tmp/candidate/files"
uid="$(id -u)"; gid="$(id -g)"
docker run --rm \
  --mount "type=bind,src=$tmp/nas,dst=/nas,readonly" \
  --mount "type=bind,src=$tmp/previous,dst=/previous,readonly" \
  --mount "type=bind,src=$tmp/candidate,dst=/backup" \
  --env "HOST_UID=$uid" --env "HOST_GID=$gid" \
  "$image" sh -ec '
    command -v rsync
    rsync -rptcog --chown="$HOST_UID:$HOST_GID" --exclude="/.image-staging/" \
      --link-dest=/previous/files/ /nas/ /backup/files/
    changes="$(rsync -rptcogni --chown="$HOST_UID:$HOST_GID" --delete \
      --exclude="/.image-staging/" /nas/ /backup/files/)"
    [ -z "$changes" ] || { echo "FAIL: checksum mismatch $changes" >&2; exit 1; }
  '
[[ "$(cat "$tmp/candidate/files/keep.txt")" == unchanged ]]
[[ "$(cat "$tmp/candidate/files/change.txt")" == updated ]]
[[ "$(cat "$tmp/candidate/files/add.txt")" == new ]]
[[ ! -e "$tmp/candidate/files/delete.txt" && ! -e "$tmp/candidate/files/.image-staging" ]]
[[ "$(stat -c %i "$tmp/previous/files/keep.txt")" == "$(stat -c %i "$tmp/candidate/files/keep.txt")" ]]
[[ "$(cat "$tmp/previous/files/change.txt")" == old ]]
printf 'PASS: isolated Docker rsync; changed/add/delete, inode reuse, exclusion, source immutability\n'
