#!/usr/bin/env bash
# Read-only host integration probe; run on pluto, never enables 0036.
set -euo pipefail
if [[ $# -ne 2 ]]; then echo 'Usage: verify-0036-pluto-integration.sh <db-container> <responder-container>' >&2; exit 2; fi
db="$1"; responder="$2"
image="$(docker inspect --format '{{.Config.Image}}' "$db")"
[[ -n "$image" ]] || { echo 'FAIL: no DB maintenance image' >&2; exit 1; }
volume="$(docker inspect --format '{{json .Mounts}}' "$responder" | python3 -c 'import json,sys; a=[m["Name"] for m in json.load(sys.stdin) if m.get("Destination")=="/data/files" and m.get("Type")=="volume"]; assert len(a)==1, "expected exactly one /data/files Docker volume"; print(a[0])')"
echo "PASS: selected maintenance image: $image"
echo "PASS: responder /data/files volume: $volume"
docker run --rm --network none --read-only --mount "type=volume,src=$volume,dst=/nas,readonly" "$image" sh -ec '
  command -v rsync >/dev/null && rsync --version | head -n 1
  test -d /nas
  echo "PASS: rsync available and NAS volume mounted read-only"
'
echo 'PASS: non-mutating Docker integration probe complete'
echo 'NOTE: source-generation pinning and disposable end-to-end rehearsal remain mandatory before enabling 0036.'
