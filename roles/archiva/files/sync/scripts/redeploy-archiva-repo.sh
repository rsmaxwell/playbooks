#!/usr/bin/env bash
set -euo pipefail

# Redeploy all artifacts from an on-disk Archiva (Maven2 layout) repository
# to another repository URL via Maven deploy:deploy-file.
#
# Usage:
#   ./redeploy-archiva-repo.sh \
#     --src-dir /path/to/archiva/repositories/releases \
#     --dst-url "https://pluto.rsmaxwell.co.uk/archiva/repository/releases2" \
#     --dst-id  "releases2" \
#     --settings /path/to/settings.xml \
#     [--dry-run]
#
# Notes:
# - Uses "mvn deploy:deploy-file" for each artifact file.
# - You must have credentials for --dst-id in the provided settings.xml.
# - For snapshots: deploy-file can deploy, but timestamped snapshots behave differently
#   (see notes below).

DRY_RUN=0
SRC_DIR=""
DST_URL=""
DST_ID=""
SETTINGS=""

usage() {
  cat <<EOF
Usage:
  $0 --src-dir <dir> --dst-url <url> --dst-id <id> --settings <settings.xml> [--dry-run]

Required:
  --src-dir    On-disk path of the source repository (Maven2 layout)
  --dst-url    Target repository base URL (e.g. https://host/archiva/repository/releases2)
  --dst-id     Server id in settings.xml (<server><id>...)</id></server>
  --settings   Path to Maven settings.xml containing credentials for --dst-id

Optional:
  --dry-run    Print what would be deployed without uploading
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src-dir)   SRC_DIR="${2:-}"; shift 2;;
    --dst-url)   DST_URL="${2:-}"; shift 2;;
    --dst-id)    DST_ID="${2:-}"; shift 2;;
    --settings)  SETTINGS="${2:-}"; shift 2;;
    --dry-run)   DRY_RUN=1; shift;;
    -h|--help)   usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

if [[ -z "$SRC_DIR" || -z "$DST_URL" || -z "$DST_ID" || -z "$SETTINGS" ]]; then
  usage
  exit 2
fi

if [[ ! -d "$SRC_DIR" ]]; then
  echo "ERROR: --src-dir not a directory: $SRC_DIR" >&2
  exit 2
fi

if [[ ! -f "$SETTINGS" ]]; then
  echo "ERROR: --settings not found: $SETTINGS" >&2
  exit 2
fi

# Normalize: remove trailing slash
SRC_DIR="${SRC_DIR%/}"
DST_URL="${DST_URL%/}"

# Common artifact extensions you likely want to redeploy.
# Add more if you store other artifact types.
ART_EXT_RE='.*\.(pom|jar|war|ear|zip|tar|tar\.gz|tgz|rar|aar|nar|so|dll|exe)$'

# Files to skip (metadata, checksums, signatures)
should_skip() {
  local f="$1"
  local base
  base="$(basename "$f")"

  [[ "$base" == maven-metadata.xml* ]] && return 0
  [[ "$base" == *.sha1 || "$base" == *.md5 || "$base" == *.sha256 || "$base" == *.sha512 ]] && return 0
  [[ "$base" == *.asc ]] && return 0
  return 1
}

# Given a file path under $SRC_DIR, derive:
# - groupId (dot separated)
# - artifactId
# - version
# - packaging (from extension, or 'pom' for pom)
#
# Expected layout:
#   <repo>/<group path>/<artifactId>/<version>/<artifactId>-<version>(-classifier).<ext>
#
# This works for standard Maven2 repo paths.
derive_coords() {
  local full="$1"
  local rel="${full#$SRC_DIR/}"

  # Split into path segments
  IFS='/' read -r -a parts <<<"$rel"
  local n="${#parts[@]}"

  # Need at least: group/a/b, artifactId, version, filename => n >= 4
  if (( n < 4 )); then
    return 1
  fi

  local filename="${parts[n-1]}"
  local version="${parts[n-2]}"
  local artifactId="${parts[n-3]}"

  # group path is everything before artifactId
  local groupPath=""
  local i
  for (( i=0; i<n-3; i++ )); do
    if [[ -z "$groupPath" ]]; then
      groupPath="${parts[i]}"
    else
      groupPath="${groupPath}.${parts[i]}"
    fi
  done

  # Packaging from extension (special-case pom)
  local packaging=""
  if [[ "$filename" == *.pom ]]; then
    packaging="pom"
  else
    packaging="${filename##*.}"
    # Handle .tar.gz / .tar etc (crude but okay)
    if [[ "$filename" == *.tar.gz ]]; then packaging="tar.gz"; fi
  fi

  printf '%s\n' "$groupPath|$artifactId|$version|$packaging"
}

# Derive classifier (if any) from filename.
# Pattern:
#   artifactId-version(-classifier).ext
# For snapshot timestamped:
#   artifactId-1.0-20260215.123456-7(-classifier).jar  (won't match version exactly)
# We'll handle timestamped snapshots specially: classifier extraction becomes unreliable.
derive_classifier_release_like() {
  local artifactId="$1"
  local version="$2"
  local filename="$3"
  local packaging="$4"

  local base="$filename"
  # strip extension
  if [[ "$packaging" == "tar.gz" ]]; then
    base="${base%.tar.gz}"
  else
    base="${base%.*}"
  fi

  local prefix="${artifactId}-${version}"
  if [[ "$base" == "$prefix" ]]; then
    echo ""
    return 0
  fi

  if [[ "$base" == "$prefix-"* ]]; then
    echo "${base#$prefix-}"
    return 0
  fi

  # doesn't look like release-like naming
  echo ""
  return 0
}

deploy_one() {
  local file="$1"
  local coords="$2"
  local groupId artifactId version packaging
  IFS='|' read -r groupId artifactId version packaging <<<"$coords"
  local filename
  filename="$(basename "$file")"

  local classifier=""
  classifier="$(derive_classifier_release_like "$artifactId" "$version" "$filename" "$packaging")"

  # Try to locate a POM:
  # - if file itself is a .pom, use it as pomFile
  # - else prefer sibling <artifactId>-<version>.pom
  #   (for some artifacts it may not exist; deploy-file can generate a POM but that is undesirable)
  local dir
  dir="$(dirname "$file")"
  local pomFile=""

  if [[ "$packaging" == "pom" ]]; then
    pomFile="$file"
  else
    local expectedPom="${dir}/${artifactId}-${version}.pom"
    if [[ -f "$expectedPom" ]]; then
      pomFile="$expectedPom"
    fi
  fi

  # Build mvn command
  local cmd=(mvn -s "$SETTINGS" -B -q deploy:deploy-file
    "-Durl=${DST_URL}"
    "-DrepositoryId=${DST_ID}"
    "-DgroupId=${groupId}"
    "-DartifactId=${artifactId}"
    "-Dversion=${version}"
    "-Dpackaging=${packaging}"
    "-Dfile=${file}"
    "-DgeneratePom=false"
  )

  # attach classifier if present
  if [[ -n "$classifier" ]]; then
    cmd+=("-Dclassifier=${classifier}")
  fi

  # attach pom if we found one
  if [[ -n "$pomFile" && "$pomFile" != "$file" ]]; then
    cmd+=("-DpomFile=${pomFile}")
  fi

  # For POM artifacts, generatePom=false and file is the pom.
  # No need for pomFile.

  if (( DRY_RUN )); then
    echo "DRY-RUN: ${groupId}:${artifactId}:${version} (${packaging}) classifier='${classifier}' file='${file}' pom='${pomFile}'"
    return 0
  fi

  echo "Deploying: ${groupId}:${artifactId}:${version} (${packaging}) ${classifier:+classifier=${classifier} }<- ${filename}"
  "${cmd[@]}"
}

echo "Source dir : $SRC_DIR"
echo "Dest URL   : $DST_URL"
echo "Dest id    : $DST_ID"
echo "Settings   : $SETTINGS"
echo "Dry run    : $DRY_RUN"
echo

# Find candidate files
# We filter by extension regex and skip metadata/checksums/signatures
mapfile -t files < <(find "$SRC_DIR" -type f \
  | grep -E -i "$ART_EXT_RE" \
  | sort)

if (( ${#files[@]} == 0 )); then
  echo "No artifact files found under $SRC_DIR"
  exit 0
fi

total=0
ok=0
skipped=0
failed=0

for f in "${files[@]}"; do
  (( total++ )) || true

  if should_skip "$f"; then
    (( skipped++ )) || true
    continue
  fi

  coords="$(derive_coords "$f" || true)"
  if [[ -z "$coords" ]]; then
    echo "SKIP (can't derive coords): $f"
    (( skipped++ )) || true
    continue
  fi

  # Snapshot timestamped file handling note:
  # If the file name is timestamped snapshot, classifier detection + pom matching may be imperfect.
  # We still attempt deploy; if it fails, you may need a snapshot-specific redeploy path.
  if deploy_one "$f" "$coords"; then
    (( ok++ )) || true
  else
    echo "FAILED: $f" >&2
    (( failed++ )) || true
  fi
done

echo
echo "Done. total=$total ok=$ok skipped=$skipped failed=$failed"
(( failed == 0 ))
