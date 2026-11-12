#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./latest-maven-version.sh <repo_base_url> <groupId> <artifactId>
#
# Example:
#   ./latest-maven-version.sh \
#     "https://pluto.rsmaxwell.co.uk/archiva/repository/releases" \
#     "com.rsmaxwell.example" \
#     "example-c_linux_amd64"

repo_base_url="${1:-}"
group_id="${2:-}"
artifact_id="${3:-}"

if [[ -z "$repo_base_url" || -z "$group_id" || -z "$artifact_id" ]]; then
  echo "Usage: $0 <repo_base_url> <groupId> <artifactId>" >&2
  exit 2
fi

# Convert groupId com.example.foo -> com/example/foo
group_path="${group_id//./\/}"

# Construct metadata URL
repo_base_url="${repo_base_url%/}"
url="${repo_base_url}/${group_path}/${artifact_id}/maven-metadata.xml"

# Fetch with HTTP status
tmp="$(mktemp)"
cleanup() { rm -f "$tmp"; }
trap cleanup EXIT

http_code="$(
  curl -fsSL -o "$tmp" -w '%{http_code}' "$url" 2>/dev/null || true
)"

# If curl failed completely, http_code may be empty
if [[ -z "$http_code" ]]; then
  echo "ERROR: failed to fetch metadata (network/curl failure): $url" >&2
  exit 2
fi

if [[ "$http_code" == "404" ]]; then
  echo "NOT FOUND: $url" >&2
  exit 1
fi

if [[ "$http_code" != "200" ]]; then
  echo "ERROR: unexpected HTTP status $http_code for $url" >&2
  exit 2
fi

xml="$(cat "$tmp")"

# Extract version:
# Prefer <release>, then <latest>, else fall back to last <version> in <versions>.
extract_tag() {
  local tag="$1"
  echo "$xml" | tr -d '\n' | sed -n "s:.*<${tag}>\\([^<]*\\)</${tag}>.*:\\1:p"
}

version="$(extract_tag release)"
if [[ -z "$version" ]]; then
  version="$(extract_tag latest)"
fi

if [[ -z "$version" ]]; then
  # Fallback: pick the last <version>...</version> entry
  # This assumes metadata lists versions in ascending order (common but not guaranteed).
  version="$(
    echo "$xml" |
      tr -d '\r' |
      sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' |
      tail -n 1
  )"
fi

if [[ -z "$version" ]]; then
  echo "ERROR: could not parse a version from metadata at $url" >&2
  exit 2
fi

# Success: print version
echo "$version"
exit 0
