#!/usr/bin/env bash
# 0036 Gate E: source-only, read-only dependency reconciliation.
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 PLAYBOOKS_ROOT DIARIES_ROOT" >&2; exit 2
fi
playbooks=$(cd "$1" && pwd -P)
diaries=$(cd "$2" && pwd -P)
for root in "$playbooks" "$diaries"; do
  test -d "$root" || { echo "Missing source root: $root" >&2; exit 2; }
done
printf 'Gate E source audit (read-only)\n'
printf 'Playbooks: %s\nDiaries: %s\n' "$playbooks" "$diaries"
for root in "$playbooks" "$diaries"; do
  printf '\n== %s ==\n' "$root"
  if [ -d "$root/.git" ]; then
    git -C "$root" rev-parse HEAD
    git -C "$root" status --short
  fi
  for term in 'diaries_0036_' 'DIARIES_0036_' 'pre-0036-rollback' 'publish-preflight' 'fixed-capture' 'fixed-destination'; do
    printf '\n-- references: %s --\n' "$term"
    grep -RIlF --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=build --exclude-dir=dist --exclude-dir=change-control --include='*.yaml' --include='*.yml' --include='*.j2' --include='*.sh' --include='*.py' --include='*.service' --include='*.env' --include='*.ps1' "$term" "$root" 2>/dev/null | sed "s|^$root/||" | sort || true
  done
done
printf '\nRead-only source audit completed. No deployment or deletion performed.\n'
