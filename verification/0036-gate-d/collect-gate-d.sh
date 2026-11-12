#!/usr/bin/env bash
# Read-only 0036 Gate D evidence capture. Run on mango after unattended cycles.
set -euo pipefail
umask 077
out="${1:-$PWD/0036-gate-d-evidence-$(date -u +%Y%m%d-%H%M%SZ)}"
mkdir -p -- "$out"
printf 'Collected at %s UTC\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$out/collection.txt"
# Capture output AND return codes without aborting the rest of the evidence capture.
collect() {
  local host="$1" label="$2" command="$3" rc=0
  echo "Collecting $host $label"
  ssh -o BatchMode=yes "$host" "bash -c $(printf '%q' "$command")" >"$out/${host}-${label}.txt" 2>&1 || rc=$?
  printf '%s %s rc=%s\n' "$host" "$label" "$rc" >> "$out/collection.txt"
}
# Journals are system records: collect as root without prompting. journalctl can
# exit zero with no entries; distinguish that from real log evidence.
collect_journal() {
  local host="$1" label="$2" unit="$3" file="$out/${1}-${2}.txt"
  local rc=0
  echo "Collecting $host $label (privileged journal)"
  ssh -o BatchMode=yes "$host" "sudo -n journalctl --quiet --utc --since '2026-10-17 00:00:00 UTC' -u '$unit' --no-pager -o short-iso" >"$file" 2>&1 || rc=$?
  if (( rc != 0 )); then
    printf '%s %s rc=%s status=ERROR (journal access/command failed)\n' "$host" "$label" "$rc" >> "$out/collection.txt"
  elif [[ ! -s "$file" ]]; then
    printf 'NO_JOURNAL_ENTRIES since 2026-10-17T00:00:00Z for %s\n' "$unit" >"$file"
    printf '%s %s rc=0 status=EMPTY (no eligible journal entries)\n' "$host" "$label" >> "$out/collection.txt"
  else
    printf '%s %s rc=0 status=ENTRIES\n' "$host" "$label" >> "$out/collection.txt"
  fi
}
collect pluto timer 'systemctl show diaries-complete-backup-publish.timer -p ActiveState -p UnitFileState -p Persistent -p NextElapseUSecRealtime; systemctl cat diaries-complete-backup-publish.service'
collect_journal pluto capture-journal diaries-complete-backup-publish.service
collect pluto capture-current 'python3 - <<"PY2"
import json,pathlib,hashlib
p=pathlib.Path("/home/richard/projects/diaries/data")
for f in [p/"diaries-backup/dataset-manifest.json",p/".diaries-backup-fixed-verified.json"]:
 print("PATH",f,"SYMLINK",f.is_symlink(),"EXISTS",f.is_file())
 if f.is_file():
  d=f.read_bytes(); print("SHA256",hashlib.sha256(d).hexdigest()); j=json.loads(d)
  for k in ("backupId","logicalDataset","snapshotEligible","manifestSha256","verifiedAt"):
   if k in j: print(k,j[k])
PY2'
collect mars timers 'for t in diaries-pull.timer btrfs-snapshot-create.timer btrfs-snapshot-prune.timer btrfs-native-push.timer; do echo "### $t"; systemctl show "$t" -p ActiveState -p UnitFileState -p Persistent -p NextElapseUSecRealtime; done'
collect_journal mars pull-journal diaries-pull.service
collect_journal mars snapshot-journal btrfs-snapshot-create.service
collect_journal mars push-journal btrfs-native-push.service
collect mars pull-current 'python3 - <<"PY2"
import pathlib,json,hashlib
p=pathlib.Path("/media/usb/@data/backup")
for f in [p/"pluto/diaries-backup/dataset-manifest.json",p/".diaries-snapshot-verified.json"]:
 print("PATH",f,"SYMLINK",f.is_symlink(),"EXISTS",f.is_file())
 if f.is_file():
  d=f.read_bytes(); print("SHA256",hashlib.sha256(d).hexdigest());j=json.loads(d)
  for k in ("backupId","logicalDataset","snapshotEligible","manifestSha256","verifiedAt","datasetRelativePath"):
   if k in j: print(k,j[k])
PY2'
collect mars snapshots 'sudo -n btrfs subvolume list -o /media/usb/@snapshots/@data | tail -60'
collect backup receipts 'sudo -n find /@data/mars-received/.replication-state -maxdepth 1 -name "*.json" -type f -printf "%f\n" | sort | tail -30'
collect backup latest-receipt 'sudo -n python3 - <<"PY2"
import pathlib,json
p=pathlib.Path("/@data/mars-received/.replication-state")
files=sorted(p.glob("*.json"))[-5:]
for f in files:
 print("RECEIPT",f.name)
 try:
  o=json.loads(f.read_text());print(json.dumps(o,indent=2,sort_keys=True))
 except Exception as e: print("ERROR",str(e))
PY2'
echo "Evidence collected in $out"
echo 'NOTE: An rc=0 proves command execution, not Gate D acceptance. Review cycles/IDs/snapshots/receipts independently.'
