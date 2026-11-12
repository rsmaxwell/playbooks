#!/usr/bin/env bash
# Non-mutating 0036 Gate 3 host CIFS mount verification.
set -euo pipefail
mount_root="${1:?Usage: verify-0036-host-nas-mount.sh MOUNT_ROOT FILES_SUBPATH}"
files_relative="${2:?Usage: verify-0036-host-nas-mount.sh MOUNT_ROOT FILES_SUBPATH}"
[[ "$mount_root" == /* && "$mount_root" != / ]] || { echo 'FAIL: invalid mount root' >&2; exit 1; }
[[ "$files_relative" != /* && "$files_relative" != *'..'* && "$files_relative" != *$'\n'* ]] || { echo 'FAIL: invalid relative Files path' >&2; exit 1; }
findmnt -rn --mountpoint "$mount_root" -t cifs >/dev/null || { echo 'BLOCKED: host CIFS mount missing' >&2; exit 2; }
opts="$(findmnt -rn --mountpoint "$mount_root" -o OPTIONS)"
case ",$opts," in *,ro,*) ;; *) echo 'FAIL: mount is not read-only' >&2; exit 1;; esac
files="$mount_root/$files_relative"
[[ -d "$files" && -r "$files" ]] || { echo 'BLOCKED: expected mounted Files directory unavailable' >&2; exit 2; }
[[ "$(realpath -m "$files")" == "$(realpath -m "$mount_root")/"* ]] || { echo 'FAIL: Files path escapes mount root' >&2; exit 1; }
echo 'PASS: separate read-only CIFS host mount present'
echo 'PASS: configured Files selector accessible within mounted share'
echo 'NOTE: production Docker CIFS volume was not modified or accessed'
