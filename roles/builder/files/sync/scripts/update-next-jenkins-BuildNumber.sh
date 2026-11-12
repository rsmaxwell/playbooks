#!/usr/bin/env bash
set -euo pipefail

# Expects these env vars to be set by the caller:
#   JOB_FULL_NAME
#   DEP_GROUP
#   DEP_ARTIFACT
#   ARCHIVA_REPO_URL
#   JENKINS_CLI_SSH_HOST
#
# Optional:
#   SCRIPT_DIR (path to helper scripts).

# ----------------------------
# Helpers
# ----------------------------

err() { echo "ERROR: $*" >&2; }

exit_other() { err "$*"; exit 2; }

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    exit_other "Missing required env var: $name"
  fi
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || exit_other "Missing required command: $1"
}

# Extract last numeric run from a version string:
#  "0.0.1.7" -> 7, "2024.08.15" -> 15, "7-SNAPSHOT" -> 7
extract_build_num() {
  local ver="$1"
  if [[ "$ver" =~ ([0-9]+)([^0-9]*)$ ]]; then
    echo "${BASH_REMATCH[1]}"
    return 0
  fi
  return 1
}

# Query current nextBuildNumber via Jenkins API (Groovy)
get_current_next() {
  local job="$1"
  ssh "${JENKINS_CLI_SSH_HOST}" groovy = <<GROOVY
import jenkins.model.Jenkins

def jobFullName = "${job}"
def item = Jenkins.instance.getItemByFullName(jobFullName)
if (item == null) {
  println "ERROR: job not found: " + jobFullName
  System.exit(3)
}
println item.getNextBuildNumber()
GROOVY
}

# Set nextBuildNumber via Jenkins API (Groovy)
set_next() {
  local job="$1"
  local desired="$2"
  ssh "${JENKINS_CLI_SSH_HOST}" groovy = <<GROOVY
import jenkins.model.Jenkins

def jobFullName = "${job}"
def desiredNext = ${desired} as int

def item = Jenkins.instance.getItemByFullName(jobFullName)
if (item == null) {
  println "ERROR: job not found: " + jobFullName
  System.exit(3)
}

def currentNext = item.getNextBuildNumber()
def last = item.getLastBuild()
def lastNum = (last != null ? last.getNumber() : 0)

// Guardrails: don't go backwards; don't set <= last build
def effective = desiredNext
if (effective <= lastNum) effective = lastNum + 1
if (effective < currentNext) effective = currentNext

item.updateNextBuildNumber(effective)
item.save()

println effective
GROOVY
}

# ----------------------------
# Validate inputs
# ----------------------------

require_cmd ssh
require_cmd sed
require_cmd curl

require_env JOB_FULL_NAME
require_env DEP_GROUP
require_env DEP_ARTIFACT
require_env ARCHIVA_REPO_URL
require_env JENKINS_CLI_SSH_HOST

LATEST_SCRIPT="${SCRIPT_DIR}/latest-maven-version.sh"

if [[ ! -x "$LATEST_SCRIPT" ]]; then
  exit_other "Helper script not found or not executable: $LATEST_SCRIPT"
fi

# ----------------------------
# 1) Resolve latest version from repository
# ----------------------------

set +e
latest_version="$("$LATEST_SCRIPT" "$ARCHIVA_REPO_URL" "$DEP_GROUP" "$DEP_ARTIFACT")"
rc=$?
set -e

case "$rc" in
  0) ;;
  1)
    # metadata not found (HTTP 404)
    err "Metadata not found for ${DEP_GROUP}:${DEP_ARTIFACT} at ${ARCHIVA_REPO_URL}"
    exit 1
    ;;
  2)
    err "Error resolving metadata for ${DEP_GROUP}:${DEP_ARTIFACT} at ${ARCHIVA_REPO_URL}"
    exit 2
    ;;
  *)
    err "Unexpected exit code $rc from $LATEST_SCRIPT"
    exit 2
    ;;
esac

latest_version="$(echo "$latest_version" | tr -d '\r' | tail -n 1)"
if [[ -z "$latest_version" ]]; then
  exit_other "Resolved version is empty"
fi

# IMPORTANT: print latest version to STDOUT for the caller to capture
# (We do it now; any logging goes to STDERR.)
echo "$latest_version"

# ----------------------------
# 2) Extract numeric build number from the version
# ----------------------------

if ! latest_build="$(extract_build_num "$latest_version")"; then
  exit_other "Could not parse numeric build number from version: '$latest_version'"
fi

if ! [[ "$latest_build" =~ ^[0-9]+$ ]]; then
  exit_other "Parsed build number is not numeric: '$latest_build'"
fi

echo "Resolved ${DEP_GROUP}:${DEP_ARTIFACT} latest version: ${latest_version} (build ${latest_build})" >&2

# ----------------------------
# 3) Query current nextBuildNumber from Jenkins
# ----------------------------

set +e
current_next="$(get_current_next "$JOB_FULL_NAME" 2>/dev/null)"
groovy_rc=$?
set -e

if [[ "$groovy_rc" -ne 0 ]]; then
  exit_other "Failed to query nextBuildNumber for job '$JOB_FULL_NAME' (ssh/groovy rc=$groovy_rc)"
fi

current_next="$(echo "$current_next" | tr -d '\r' | tail -n 1)"
if ! [[ "$current_next" =~ ^[0-9]+$ ]]; then
  exit_other "Invalid nextBuildNumber returned for '$JOB_FULL_NAME': '$current_next'"
fi

echo "Job '${JOB_FULL_NAME}' current nextBuildNumber: ${current_next}" >&2

# ----------------------------
# 4) Update nextBuildNumber if needed
# ----------------------------

if (( latest_build >= current_next )); then
  target_next=$(( latest_build + 1 ))
  echo "Updating nextBuildNumber to ${target_next} (because ${latest_build} >= ${current_next})" >&2

  set +e
  new_next="$(set_next "$JOB_FULL_NAME" "$target_next" 2>/dev/null)"
  set_rc=$?
  set -e

  if [[ "$set_rc" -ne 0 ]]; then
    exit_other "Failed to set nextBuildNumber for '$JOB_FULL_NAME' (ssh/groovy rc=$set_rc)"
  fi

  new_next="$(echo "$new_next" | tr -d '\r' | tail -n 1)"
  if ! [[ "$new_next" =~ ^[0-9]+$ ]]; then
    exit_other "Invalid response from set_next: '$new_next'"
  fi

  echo "OK: nextBuildNumber for '${JOB_FULL_NAME}' is now ${new_next}" >&2
else
  echo "No change: ${latest_build} < ${current_next}" >&2
fi

exit 0
