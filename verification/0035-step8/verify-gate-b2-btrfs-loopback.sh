#!/usr/bin/env bash
# 0035 Gate B2: EXPLICITLY OPT-IN disposable Btrfs kernel send/receive tests.
# Never calls the production native-push endpoint, SSH, or the live prune command.
set -Eeuo pipefail
if [[ "${1:-}" != "--run-disposable" || $# -ne 1 ]]; then
  echo 'Usage: sudo bash verification/0035-step8/verify-gate-b2-btrfs-loopback.sh --run-disposable' >&2
  echo 'Creates and mounts three NEW 384MiB loopback images; requires root, btrfs-progs, loop and mount support.' >&2
  exit 2
fi
[[ $EUID -eq 0 ]] || { echo 'ERROR: root required for disposable mounts' >&2; exit 2; }
for cmd in mkfs.btrfs btrfs losetup mount umount truncate dd cmp sha256sum timeout; do
  command -v "$cmd" >/dev/null || { echo "SKIP: missing $cmd"; exit 77; }
done
[[ -e /dev/loop-control ]] || { echo 'SKIP: no loop-control device (run on isolated VM with loopback enabled)'; exit 77; }
# Work exclusively under a newly allocated private directory; trap owns both mounts and loops.
BASE=$(mktemp -d -p "${TMPDIR:-/tmp}" 0035-b2-loopback-XXXXXXXX)
chmod 700 "$BASE"
SRC_LOOP='' DST_LOOP='' WRONG_LOOP=''
cleanup() {
  set +e
  mountpoint -q "$BASE/wrong" && umount "$BASE/wrong"
  mountpoint -q "$BASE/dst" && umount "$BASE/dst"
  mountpoint -q "$BASE/src" && umount "$BASE/src"
  [[ -n "$WRONG_LOOP" ]] && losetup -d "$WRONG_LOOP"
  [[ -n "$DST_LOOP" ]] && losetup -d "$DST_LOOP"
  [[ -n "$SRC_LOOP" ]] && losetup -d "$SRC_LOOP"
  # Refuse cleanup if a mount is still active.
  if ! mountpoint -q "$BASE/src" && ! mountpoint -q "$BASE/dst" && ! mountpoint -q "$BASE/wrong"; then rm -rf -- "$BASE"; else echo "ALERT: mounts remain; manual cleanup needed at $BASE" >&2; fi
}
trap cleanup EXIT
mkdir "$BASE/src" "$BASE/dst" "$BASE/wrong"
truncate -s 384M "$BASE/source.img"
truncate -s 384M "$BASE/receiver.img"
truncate -s 384M "$BASE/no-parent.img"
SRC_LOOP=$(losetup --find --show "$BASE/source.img")
DST_LOOP=$(losetup --find --show "$BASE/receiver.img")
WRONG_LOOP=$(losetup --find --show "$BASE/no-parent.img")
mkfs.btrfs -q -f "$SRC_LOOP"
mkfs.btrfs -q -f "$DST_LOOP"
mkfs.btrfs -q -f "$WRONG_LOOP"
mount -t btrfs "$SRC_LOOP" "$BASE/src"
mount -t btrfs "$DST_LOOP" "$BASE/dst"
mount -t btrfs "$WRONG_LOOP" "$BASE/wrong"
btrfs subvolume create "$BASE/src/data" >/dev/null
mkdir "$BASE/src/snaps" "$BASE/dst/received"
printf '0035-b2-initial\n' > "$BASE/src/data/payload.txt"
btrfs subvolume snapshot -r "$BASE/src/data" "$BASE/src/snaps/20261015-010000Z" >/dev/null
# Verified baseline: real kernel send/receive and data round-trip.
btrfs send "$BASE/src/snaps/20261015-010000Z" | btrfs receive "$BASE/dst/received" >/dev/null
cmp "$BASE/src/snaps/20261015-010000Z/payload.txt" "$BASE/dst/received/20261015-010000Z/payload.txt"
[[ $(btrfs property get -ts "$BASE/dst/received/20261015-010000Z" ro) == 'ro=true' ]]
BASE_UUID=$(btrfs subvolume show "$BASE/src/snaps/20261015-010000Z" | awk '/^[[:space:]]*UUID:/{print $2;exit}')
RECEIVED_UUID=$(btrfs subvolume show "$BASE/dst/received/20261015-010000Z" | awk '/Received UUID:/{print $3;exit}')
[[ -n "$BASE_UUID" && "$BASE_UUID" == "$RECEIVED_UUID" ]]
echo 'PASS: kernel full send/receive; data, read-only state and received UUID match'
# A broken stream to an independent unaccepted receive directory must fail closed.
mkdir "$BASE/dst/unaccepted"
if ( set -o pipefail; btrfs send "$BASE/src/snaps/20261015-010000Z" | head -c 128 | btrfs receive "$BASE/dst/unaccepted" >/dev/null 2>&1 ); then
  echo 'FAIL: deliberately truncated full stream was accepted' >&2; exit 1
fi
[[ -f "$BASE/dst/received/20261015-010000Z/payload.txt" ]]
echo 'PASS: interrupted/truncated full stream rejected; previously accepted full baseline untouched'
# Create and accept one actual incremental, retaining the preceding read-only parent.
printf '0035-b2-incremental\n' >> "$BASE/src/data/payload.txt"
btrfs subvolume snapshot -r "$BASE/src/data" "$BASE/src/snaps/20261015-020000Z" >/dev/null
btrfs send -p "$BASE/src/snaps/20261015-010000Z" "$BASE/src/snaps/20261015-020000Z" | btrfs receive "$BASE/dst/received" >/dev/null
cmp "$BASE/src/snaps/20261015-020000Z/payload.txt" "$BASE/dst/received/20261015-020000Z/payload.txt"
[[ $(btrfs property get -ts "$BASE/dst/received/20261015-020000Z" ro) == 'ro=true' ]]
echo 'PASS: kernel incremental send/receive; parent preserved and payload matches'
# Invalid parent: destination does not possess required parent. A send stream must fail to receive on a separate filesystem.
mkdir "$BASE/wrong/received"
if ( set -o pipefail; btrfs send -p "$BASE/src/snaps/20261015-010000Z" "$BASE/src/snaps/20261015-020000Z" | btrfs receive "$BASE/wrong/received" >/dev/null 2>&1 ); then
  echo 'FAIL: missing receiver parent unexpectedly accepted incremental' >&2; exit 1
fi
echo 'PASS: incremental receive on independent filesystem without parent rejected'
# Truncated incremental stream to a separate destination containing a valid parent.
mkdir "$BASE/dst/interrupted"
btrfs send "$BASE/src/snaps/20261015-010000Z" | btrfs receive "$BASE/dst/interrupted" >/dev/null
if ( set -o pipefail; btrfs send -p "$BASE/src/snaps/20261015-010000Z" "$BASE/src/snaps/20261015-020000Z" | head -c 128 | btrfs receive "$BASE/dst/interrupted" >/dev/null 2>&1 ); then
  echo 'FAIL: deliberately truncated incremental stream was accepted' >&2; exit 1
fi
cmp "$BASE/src/snaps/20261015-020000Z/payload.txt" "$BASE/dst/received/20261015-020000Z/payload.txt"
echo 'PASS: truncated incremental stream rejected; existing accepted incremental untouched'
echo 'GATE B2 disposable kernel loopback tests PASS'
echo 'NOT TESTED: SSH disconnect/acknowledgement; kernel ENOSPC; production receiver receipts; complete schema-2 restore'
