#!/usr/bin/env bash
set -euo pipefail
# Read-only, run from mango using existing SSH host aliases.
# No deletion, Btrfs changes, Ansible actions or timer restarts.
output=${1:?Usage: assess-legacy-generations.sh OUTPUT_DIRECTORY}
mkdir -p -- "$output"
for host in pluto mars; do
  if [[ "$host" == pluto ]]; then base=/home/richard/projects/diaries/data; else base=/media/usb/@data/backup/pluto; fi
  echo "Collecting read-only inventory from $host"
  ssh -o BatchMode=yes "$host" bash -s -- "$base" > "$output/$host-generations.txt" 2>&1 <<'REMOTE'
set -euo pipefail
base=$1
printf 'HOST=%s UTC=%s BASE=%s\n' "$(hostname)" "$(date -u +%FT%TZ)" "$base"
for path in "$base/diaries-backup" "$base/diaries-backup.pre-0036-rollback" "$base/.diaries-backup-generations"; do
  if [[ -e $path || -L $path ]]; then
    stat -c '%F | %n | %N' -- "$path"
    realpath -e -- "$path" || true
  else printf 'MISSING %s\n' "$path"; fi
done
printf '\nGENERATION ENTRIES\n'
if [[ -d "$base/.diaries-backup-generations" ]]; then
  find "$base/.diaries-backup-generations" -mindepth 1 -maxdepth 1 -printf '%y | %f | %p\n' | sort
fi
printf '\nSERVICE DEFINITIONS (names and commands)\n'
for service in diaries-complete-backup-publish.service diaries-pull.service; do
  if systemctl cat "$service" >/dev/null 2>&1; then
    systemctl cat "$service" | grep -E '^(# /|ExecStart=|EnvironmentFile=)' || true
  fi
done
printf '\nACTIVE/TIMER STATUS\n'
for unit in diaries-complete-backup-publish.timer diaries-pull.timer btrfs-snapshot-create.timer btrfs-snapshot-prune.timer btrfs-native-push.timer; do
  if systemctl list-unit-files "$unit" --no-legend --no-pager | grep -q .; then
    printf '%s enabled=%s active=%s\n' "$unit" "$(systemctl is-enabled "$unit" 2>/dev/null || true)" "$(systemctl is-active "$unit" 2>/dev/null || true)"
  fi
done
REMOTE
done
printf 'Complete: %s\n' "$output"
