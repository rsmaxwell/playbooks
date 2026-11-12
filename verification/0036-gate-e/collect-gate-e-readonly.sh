#!/usr/bin/env bash
# 0036 Gate E: read-only cross-host retirement inventory. Run from mango.
set -euo pipefail
out="${1:?Usage: $0 OUTPUT_DIRECTORY}"
if [[ -e "$out" ]]; then echo "Refusing to overwrite: $out" >&2; exit 2; fi
mkdir -m 700 -p "$out"
log="$out/collection.txt"
printf 'Collected UTC: %s\n' "$(date -u +%FT%TZ)" > "$log"
run() {
  local host="$1" key="$2" cmd="$3"
  local file="$out/${host}-${key}.txt"
  local rc=0
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$host" "bash -lc $(printf '%q' "$cmd")" > "$file" 2>&1 || rc=$?
  printf '%s %s rc=%s\n' "$host" "$key" "$rc" | tee -a "$log"
}
run pluto timers 'systemctl is-enabled diaries-complete-backup-publish.timer; systemctl is-active diaries-complete-backup-publish.timer; systemctl cat diaries-complete-backup-publish.service'
run pluto publication 'for p in /home/richard/projects/diaries/data/diaries-backup /home/richard/projects/diaries/data/diaries-backup.pre-0036-rollback /home/richard/projects/diaries/data/.diaries-backup-generations; do stat -c "%F %n %N" "$p" 2>&1 || :; done; ls -ld /home/richard/projects/diaries/data/.diaries-backup-generations/* 2>/dev/null || :'
run pluto scripts 'ls -ld /home/richard/projects/diaries/scripts/pre-0036-rollback /home/richard/projects/diaries/scripts/backup-dataset.sh 2>&1 || :; grep -RIl "0036" /home/richard/projects/diaries/scripts 2>/dev/null | head -60 || :'
run mars timers 'for x in diaries-pull.timer btrfs-snapshot-create.timer btrfs-snapshot-prune.timer btrfs-native-push.timer; do printf "%s " "$x"; systemctl is-enabled "$x"; systemctl is-active "$x"; done; systemctl cat diaries-pull.service 2>/dev/null || :'
run mars publication 'for p in /media/usb/@data/backup/pluto/diaries-backup /media/usb/@data/backup/pluto/diaries-backup.pre-0036-rollback /media/usb/@data/backup/pluto/.diaries-backup-generations /media/usb/@data/backup/.diaries-snapshot-verified.json; do stat -c "%F %n %N" "$p" 2>&1 || :; done; ls -ld /media/usb/@data/backup/pluto/.diaries-backup-generations/* 2>/dev/null || :'
run mars snapshot-state 'findmnt -t btrfs -o TARGET,SOURCE,FSROOT,OPTIONS; ls -la /media/usb/@snapshots | head -45; ls -ld /media/usb/@data/.snapshots 2>&1 || :'
run backup receiving 'findmnt -t btrfs -o TARGET,SOURCE,FSROOT,OPTIONS; ls -ld /@data/mars-received /@data/mars-received/@data /@data/.snapshots /@snapshots 2>&1 || :; ls -1 /@data/mars-received/@data 2>&1 | tail -25'
run pluto revision 'cd /home/richard/projects/diaries && git rev-parse HEAD 2>/dev/null || :'
run mars revision 'cd /home/richard/playbooks && git rev-parse HEAD 2>/dev/null || :'
printf 'READ-ONLY: No deployment, timer restart, prune, snapshot deletion, or generation removal performed.\n' | tee -a "$log"
