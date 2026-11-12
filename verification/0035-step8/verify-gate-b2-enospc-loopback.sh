#!/usr/bin/env bash
# 0035 Gate B2: opt-in actual Btrfs ENOSPC receive failure on disposable loopback volumes only.
set -Eeuo pipefail
if [[ $# != 1 || ${1:-} != --run-disposable ]]; then
  echo 'Usage: sudo bash verify-gate-b2-enospc-loopback.sh --run-disposable' >&2; exit 2
fi
(( EUID == 0 )) || { echo 'ERROR: root required' >&2; exit 2; }
for cmd in mkfs.btrfs btrfs losetup mount umount mountpoint truncate dd cmp awk timeout; do
  command -v "$cmd" >/dev/null || { echo "SKIP: missing $cmd"; exit 77; }
done
[[ -e /dev/loop-control ]] || { echo 'SKIP: no loop device support'; exit 77; }
BASE=$(mktemp -d -p "${TMPDIR:-/tmp}" 0035-b2-enospc-XXXXXXXX)
chmod 700 "$BASE"
SRC_LOOP='' DST_LOOP=''
cleanup() {
  set +e
  mountpoint -q "$BASE/dst" && umount "$BASE/dst"
  mountpoint -q "$BASE/src" && umount "$BASE/src"
  [[ -n "$DST_LOOP" ]] && losetup -d "$DST_LOOP"
  [[ -n "$SRC_LOOP" ]] && losetup -d "$SRC_LOOP"
  if ! mountpoint -q "$BASE/src" && ! mountpoint -q "$BASE/dst"; then
    rm -rf -- "$BASE"
  else
    echo "ALERT: mounted test volume retained at $BASE" >&2
  fi
}
trap cleanup EXIT
mkdir "$BASE/src" "$BASE/dst"
truncate -s 384M "$BASE/src.img"
truncate -s 384M "$BASE/dst.img"
SRC_LOOP=$(losetup --find --show "$BASE/src.img")
DST_LOOP=$(losetup --find --show "$BASE/dst.img")
mkfs.btrfs -q -f "$SRC_LOOP"
mkfs.btrfs -q -f "$DST_LOOP"
mount -t btrfs "$SRC_LOOP" "$BASE/src"
mount -t btrfs "$DST_LOOP" "$BASE/dst"
btrfs subvolume create "$BASE/src/data" >/dev/null
mkdir "$BASE/src/snaps" "$BASE/dst/accepted"
printf 'original accepted baseline\n' > "$BASE/src/data/key.txt"
btrfs subvolume snapshot -r "$BASE/src/data" "$BASE/src/snaps/20261015-010000Z" >/dev/null
btrfs send "$BASE/src/snaps/20261015-010000Z" | btrfs receive "$BASE/dst/accepted" >/dev/null
BASE_UUID=$(btrfs subvolume show "$BASE/src/snaps/20261015-010000Z" | awk '/^[[:space:]]*UUID:/{print $2;exit}')
[[ $(btrfs subvolume show "$BASE/dst/accepted/20261015-010000Z" | awk '/Received UUID:/{print $3;exit}') == "$BASE_UUID" ]]
[[ $(btrfs property get -ts "$BASE/dst/accepted/20261015-010000Z" ro) == 'ro=true' ]]
# Fill with incompressible data to force genuine ENOSPC, keeping baseline accepted.
# The target is disposable. No files on the real receiver are accessed.
if dd if=/dev/urandom of="$BASE/dst/pressure.bin" bs=1M count=500 status=none 2>"$BASE/pressure-error"; then
  echo 'FAIL: disposable receiver did not reach ENOSPC' >&2; exit 1
fi
if ! grep -qi 'No space left on device' "$BASE/pressure-error"; then
  echo 'FAIL: fill stopped for a reason other than ENOSPC' >&2; cat "$BASE/pressure-error" >&2; exit 1
fi
echo 'PASS: real Btrfs ENOSPC on disposable receiver'
# Even with free space exhausted, existing accepted dataset remains visible and read only.
cmp <(printf 'original accepted baseline\n') "$BASE/dst/accepted/20261015-010000Z/key.txt"
[[ $(btrfs property get -ts "$BASE/dst/accepted/20261015-010000Z" ro) == 'ro=true' ]]
echo 'PASS: previously accepted baseline remains readable and read-only under ENOSPC'
# A new full stream must not be marked accepted when the destination cannot store it.
dd if=/dev/urandom of="$BASE/src/data/large.bin" bs=1M count=64 status=none
btrfs subvolume snapshot -r "$BASE/src/data" "$BASE/src/snaps/20261015-020000Z" >/dev/null
mkdir "$BASE/dst/unaccepted"
if ( set -o pipefail; btrfs send "$BASE/src/snaps/20261015-020000Z" | btrfs receive "$BASE/dst/unaccepted" >"$BASE/receive-output" 2>&1 ); then
  echo 'FAIL: new stream unexpectedly accepted under ENOSPC' >&2; exit 1
fi
[[ ! -f "$BASE/dst/accepted/20261015-020000Z/key.txt" ]]
cmp <(printf 'original accepted baseline\n') "$BASE/dst/accepted/20261015-010000Z/key.txt"
echo 'PASS: new stream not accepted under ENOSPC; previous baseline intact'
# Remove ONLY the disposable pressure file and verify the accepted baseline survives.
rm -f -- "$BASE/dst/pressure.bin"
sync
cmp <(printf 'original accepted baseline\n') "$BASE/dst/accepted/20261015-010000Z/key.txt"
echo 'PASS: previously accepted baseline survives ENOSPC recovery'
echo 'GATE B2 actual kernel ENOSPC test PASS'
echo 'NOT TESTED: receiver receipt publication ENOSPC; real SSH disconnect/ack loss; schema-2 restore'
