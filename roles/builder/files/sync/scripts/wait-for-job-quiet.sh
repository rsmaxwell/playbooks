#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  wait-for-job-quiet.sh -H <ssh-host> -j <job-full-name> [-t timeoutSeconds] [-i pollSeconds]

Examples:
  wait-for-job-quiet.sh -H admin-at-jenkins-at-pluto -j 'example-c-pipeline/linux_amd64' -t 1200 -i 5
EOF
}

die() { echo "ERROR: $*" >&2; exit 2; }

is_uint() { [[ "${1:-}" =~ ^[0-9]+$ ]]; }

# Helper for safe quoting into a Groovy single-quoted string
groovy_sq() {
  local s="$1"
  s="${s//\\/\\\\}"   # \  -> \\
  s="${s//\'/\\\'}"   # '  -> \'
  printf "%s" "$s"
}






HOST=""
JOB_FULL_NAME=""
TIMEOUT_S=900
SLEEP_S=5

while getopts ":H:j:t:i:h" opt; do
  case "$opt" in
    H) HOST="$OPTARG" ;;
    j) JOB_FULL_NAME="$OPTARG" ;;
    t) TIMEOUT_S="$OPTARG" ;;
    i) SLEEP_S="$OPTARG" ;;
    h) usage; exit 0 ;;
    \?) usage; die "Unknown option: -$OPTARG" ;;
    :) usage; die "Missing argument for -$OPTARG" ;;
  esac
done
shift $((OPTIND - 1))

[[ -n "$HOST" ]] || { usage; die "Missing -H <ssh-host>"; }
[[ -n "$JOB_FULL_NAME" ]] || { usage; die "Missing -j <job-full-name>"; }

is_uint "$TIMEOUT_S" || die "timeout must be an integer (got: '$TIMEOUT_S')"
is_uint "$SLEEP_S"   || die "poll interval must be an integer (got: '$SLEEP_S')"
(( TIMEOUT_S > 0 ))  || die "timeout must be > 0"
(( SLEEP_S > 0 ))    || die "poll interval must be > 0"

# Optional: sanity-check job name to avoid accidental weird input
if [[ ! "$JOB_FULL_NAME" =~ ^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$ ]]; then
  die "job full name contains unexpected characters: '$JOB_FULL_NAME'"
fi

# Validate SSH connectivity
ssh -o BatchMode=yes -o ConnectTimeout=5 "$HOST" who-am-i >/dev/null \
  || die "cannot SSH to '$HOST' (check alias/keys/network)"

# Validate Jenkins CLI groovy works (fast fail if Jenkins is down)
if ! out="$(ssh "$HOST" groovy = <<< 'println("OK")' 2>/dev/null)" || [[ "$out" != "OK" ]]; then
  die "Jenkins 'groovy' CLI not working over ssh on '$HOST'"
fi

deadline=$((SECONDS + TIMEOUT_S))
while (( SECONDS < deadline )); do
  job_esc="$(groovy_sq "$JOB_FULL_NAME")"

  state="$(
    {
      printf "def fullName = '%s'\n" "$job_esc"
      cat <<'GROOVY'
import jenkins.model.Jenkins

def j = Jenkins.instance
def item = j.getItemByFullName(fullName)
if (item == null) { println("MISSING"); return }

def isQueued(taskDisplayName) {
  return j.queue.items.any { qi ->
    try { qi.task?.fullDisplayName == taskDisplayName } catch (ignored) { false }
  }
}

// Multibranch indexing
def indexingBusy = false
try {
  indexingBusy = item.metaClass.respondsTo(item, "isBuilding") ? (item.isBuilding() as boolean) : false
} catch (ignored) {}

// Branch jobs (if multibranch)
def branchBusy = false
def branchQueued = false
try {
  def children = item.metaClass.respondsTo(item, "getItems") ? item.getItems() : null
  if (children != null) {
    children.each { child ->
      try {
        def lb = child.getLastBuild()
        if (lb != null && lb.isBuilding()) branchBusy = true
        if (isQueued(child.fullDisplayName)) branchQueued = true
      } catch (ignored) {}
    }
  }
} catch (ignored) {}

// Non-multibranch job itself
def selfBusy = false
def selfQueued = false
try {
  def lb = item.getLastBuild()
  if (lb != null && lb.isBuilding()) selfBusy = trues
  selfQueued = isQueued(item.fullDisplayName)
} catch (ignored) {}

def busy = indexingBusy || branchBusy || branchQueued || selfBusy || selfQueued
println(busy ? "BUSY" : "QUIET")
GROOVY
    } | ssh "$HOST" groovy =
  )"

  case "$state" in
    QUIET) exit 0 ;;
    MISSING)
      echo "WARNING: job '${JOB_FULL_NAME}' not found yet; waiting..." >&2
      ;;
    BUSY|"")
      ;;
    *)
      echo "WARNING: unexpected state='$state'; waiting..." >&2
      ;;
  esac

  sleep "$SLEEP_S"
done

echo "WARNING: timed out waiting for job to become quiet: ${JOB_FULL_NAME}" >&2
exit 1
