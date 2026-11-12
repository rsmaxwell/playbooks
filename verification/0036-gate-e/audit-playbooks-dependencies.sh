#!/usr/bin/env bash
# 0036 Gate E: Playbooks-only source dependency audit (read-only).
set -euo pipefail
if [ "$#" -gt 1 ]; then echo "Usage: $0 [PLAYBOOKS_ROOT]" >&2; exit 2; fi
root=$(cd "${1:-$(dirname "$0")/../..}" && pwd -P)
if [ ! -d "$root/.git" ]; then echo "Not a Git working tree: $root" >&2; exit 2; fi
printf '0036 Gate E Playbooks source audit (read-only)\nRoot: %s\n' "$root"
printf 'Git commit: '; git -C "$root" rev-parse HEAD
printf 'Git status:\n'; git -C "$root" status --short
for term in 'diaries_0036_' 'DIARIES_0036_' 'pre-0036-rollback' 'publish-preflight' 'fixed-capture' 'fixed-destination'; do
  printf '\n-- references: %s --\n' "$term"
  grep -RIlF --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=build --exclude-dir=dist --exclude-dir=change-control --include='*.yaml' --include='*.yml' --include='*.j2' --include='*.sh' --include='*.py' --include='*.service' --include='*.env' --include='*.ps1' "$term" "$root" 2>/dev/null | sed "s|^$root/||" | sort || true
done
printf '\nRead-only audit completed; no deployment or deletion performed.\n'
