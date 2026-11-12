#!/usr/bin/env bash
# Real ENOSPC against the production receiver's atomic_receipt function,
# but with STATE redirected to a disposable Btrfs loopback filesystem.
set -Eeuo pipefail
[[ ${1:-} == '--run-disposable' && $# == 1 && $EUID == 0 ]] || { echo 'Usage: sudo bash ... --run-disposable' >&2; exit 2; }
for x in python3 mkfs.btrfs losetup mount umount truncate dd grep mountpoint; do command -v "$x" >/dev/null || { echo "SKIP: missing $x"; exit 77; }; done
[[ -e /dev/loop-control ]] || { echo 'SKIP: loop devices unavailable'; exit 77; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RECEIVER="$SCRIPT_DIR/../../roles/btrfs-replication/files/btrfs-native-push-receiver.py"
[[ -f "$RECEIVER" ]] || { echo 'ERROR: source receiver missing'; exit 2; }
BASE=$(mktemp -d -p "${TMPDIR:-/tmp}" 0035-receipt-enospc-XXXXXXXX)
chmod 700 "$BASE"
LOOP=''
cleanup() {
  set +e
  if mountpoint -q "$BASE/mount"; then umount "$BASE/mount"; fi
  if [[ -n "$LOOP" ]]; then losetup -d "$LOOP"; fi
  if ! mountpoint -q "$BASE/mount"; then rm -rf -- "$BASE"; else echo "ALERT: mounted test retained $BASE" >&2; fi
}
trap cleanup EXIT
mkdir "$BASE/mount"
truncate -s 384M "$BASE/disk.img"
LOOP=$(losetup --find --show "$BASE/disk.img")
mkfs.btrfs -q -f "$LOOP"
mount -t btrfs "$LOOP" "$BASE/mount"
mkdir "$BASE/mount/receipts"
export TEST_RECEIVER="$RECEIVER" TEST_STATE="$BASE/mount/receipts"
python3 - <<'PY'
import importlib.util, json, os
from pathlib import Path
spec=importlib.util.spec_from_file_location('disposable_receiver', os.environ['TEST_RECEIVER'])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.STATE=Path(os.environ['TEST_STATE'])
m.atomic_receipt({'snapshot':'20261015-010000Z','test':'original accepted receipt'})
print('PASS: baseline receipt atomically published before pressure')
PY
# Incompressible bytes fill the test Btrfs volume, not the host root filesystem.
if dd if=/dev/urandom of="$BASE/mount/pressure.bin" bs=1M count=500 status=none 2>"$BASE/fill.err"; then
  echo 'FAIL: could not trigger ENOSPC' >&2; exit 1
fi
grep -qi 'No space left on device' "$BASE/fill.err" || { cat "$BASE/fill.err" >&2; exit 1; }
python3 - <<'PY'
import importlib.util, json, os
from pathlib import Path
spec=importlib.util.spec_from_file_location('disposable_receiver',os.environ['TEST_RECEIVER'])
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
m.STATE=Path(os.environ['TEST_STATE'])
try:
    m.atomic_receipt({'snapshot':'20261015-020000Z','payload':'X'*1024*1024})
except OSError as e:
    if e.errno != 28: raise
    print('PASS: real receipt publication ENOSPC rejected')
else:
    raise AssertionError('New receipt unexpectedly accepted')
old=json.loads((m.STATE/'20261015-010000Z.json').read_text())
assert old['test']=='original accepted receipt'
assert not (m.STATE/'20261015-020000Z.json').exists()
assert not list(m.STATE.glob('.push-receipt-*'))
print('PASS: previous receipt intact, new receipt absent, temporary file cleaned')
PY
printf 'GATE B2 actual receipt-publication ENOSPC PASS\n'
