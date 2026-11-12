#!/usr/bin/env bash
set -euo pipefail
# 0036 Gate E: evidence-only inventory. Never prunes, deletes, mounts or writes remotely.
usage() { echo "Usage: $0 NEW_OUTPUT_DIRECTORY" >&2; exit 2; }
[[ $# == 1 && -n $1 ]] || usage
out=$1
[[ ! -e $out ]] || { echo "Refusing to overwrite existing output: $out" >&2; exit 2; }
mkdir -m 700 -- "$out"
printf 'Collected UTC: %s\nPurpose: read-only generation assessment; NOT deletion authorisation\n' "$(date -u +%FT%TZ)" > "$out/README.txt"
fail=0
for host in pluto mars; do
  case $host in
    pluto) base=/home/richard/projects/diaries/data ;;
    mars) base=/media/usb/@data/backup/pluto ;;
  esac
  echo "Inspecting $host (read-only)"
  if ssh -o BatchMode=yes "$host" bash -s -- "$base" > "$out/$host.txt" 2>&1 <<'REMOTE'
set -euo pipefail
base=$1
repo=$base/.diaries-backup-generations
alias=$base/diaries-backup.pre-0036-rollback
printf 'HOST=%s UTC=%s BASE=%s\n' "$(hostname)" "$(date -u +%FT%TZ)" "$base"
printf '\nROLLBACK ALIAS\n'
if [[ -L "$alias" ]]; then
  printf 'LINK=%s\n' "$(readlink -- "$alias")"
  printf 'RESOLVED=%s\n' "$(realpath -e -- "$alias" || echo BROKEN)"
else echo 'ALIAS_MISSING_OR_NOT_SYMLINK'; fi
printf '\nGENERATION METADATA\n'
if [[ ! -d "$repo" ]]; then echo 'ERROR: generation repository absent'; exit 3; fi
while IFS= read -r -d '' gen; do
  name=${gen##*/}
  printf '\n==== GENERATION %s ====\n' "$name"
  stat -c 'ENTRY_TYPE=%F MODE=%a OWNER=%U:%G' -- "$gen"
  if [[ -L "$gen" ]]; then echo 'ERROR: generation is symlink; not following'; continue; fi
  if [[ ! -d "$gen" ]]; then echo 'ERROR: generation is not directory'; continue; fi
  if sudo -n btrfs subvolume show "$gen" >/dev/null 2>&1; then
    echo 'GENERATION_BTRFS_SUBVOLUME=yes'
    sudo -n btrfs subvolume show "$gen" | grep -E '^\s*(UUID:|Received UUID:|Subvolume ID:|Flags:)' || true
  else echo 'GENERATION_BTRFS_SUBVOLUME=no_or_unavailable'; fi
  echo 'TOP_LEVEL_ENTRIES'
  find "$gen" -mindepth 1 -maxdepth 1 -printf '%y %f\n' | LC_ALL=C sort
  echo 'NESTED_SUBVOLUMES (if listing permitted)'
  if sudo -n btrfs subvolume list -o "$gen" 2>/dev/null; then :; else echo 'UNAVAILABLE'; fi
  echo 'SCHEMA2_CANDIDATE_MANIFESTS (limited depth)'
  while IFS= read -r -d '' manifest; do
    printf 'FILE=%s\n' "${manifest#"$gen"/}"
    if [[ -f "$manifest" && ! -L "$manifest" ]]; then
      sha256sum -- "$manifest" | awk '{print "SHA256=" $1}'
      python3 - "$manifest" <<'PY'
import json,sys
try:
    with open(sys.argv[1],encoding='utf-8') as f: obj=json.load(f)
    if not isinstance(obj,dict): raise ValueError('JSON root is not object')
    print('JSON_KEYS='+','.join(sorted(obj)))
    for key in ('schema_version','schemaVersion','schema','backup_id','backupId','dataset','dataset_id','datasetId','logical_dataset','logicalDataset','files_count','fileCount'):
        val=obj.get(key)
        if isinstance(val,(str,int,float,bool)):
            print('FIELD_'+key+'='+str(val)[:150].replace('\\n',' '))
    for key in ('files','entries'):
        if isinstance(obj.get(key),list): print('COUNT_'+key+'='+str(len(obj[key])))
except Exception as exc:
    print('MANIFEST_PARSE_ERROR='+type(exc).__name__+':'+str(exc)[:120])
PY
    fi
  done < <(find "$gen" -maxdepth 3 -type f \( -iname '*manifest*.json' -o -name 'dataset.json' \) -print0 2>/dev/null | sort -z)
  echo 'MANIFEST_COMPLETENESS=UNVERIFIED (this collector does not hash payload files)'
  echo 'BTRFS_SNAPSHOT_COVERAGE=UNVERIFIED (requires identity comparison to retained source snapshots)'
done < <(find "$repo" -mindepth 1 -maxdepth 1 -print0 | sort -z)
printf '\nPATH REFERENCES IN DEPLOYED SCRIPTS AND CONFIGURATION (filenames and line numbers only)\n'
# Report references, not line contents, to avoid leaking environment values or secrets.
for root in /home/richard/projects/diaries/scripts /home/richard/scripts/backup /etc/systemd/system; do
  [[ -d "$root" ]] || continue
  grep -RInlE --exclude='*.env' --exclude='*.bak' --exclude='*credentials*' \
    --exclude='*.pre-*' --exclude-dir=.git \
    '(\.diaries-backup-generations|diaries-backup\.pre-0036-rollback|20261016-003019Z)' \
    "$root" 2>/dev/null || true
done
printf '\nACTIVE SERVICES\n'
for unit in diaries-complete-backup-publish.service diaries-pull.service; do
 printf '%s=%s\n' "$unit" "$(systemctl is-active "$unit" 2>/dev/null || true)"
done
REMOTE
  then echo "$host result=COLLECTED" | tee -a "$out/summary.txt"
  else echo "$host result=ERROR (inspect $host.txt)" | tee -a "$out/summary.txt"; fail=1; fi
done
printf '\nRESULT: %s\n' "$([[ $fail == 0 ]] && echo 'collection completed; human decision required' || echo 'incomplete collection')" | tee -a "$out/summary.txt"
exit "$fail"
