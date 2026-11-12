#!/usr/bin/env bash
# Disposable SSH transport interruption on loopback only; no production endpoint.
set -Eeuo pipefail
[[ ${1:-} == '--run-disposable' && $# == 1 && $EUID == 0 ]] || { echo 'Usage: sudo bash ... --run-disposable' >&2; exit 2; }
for x in ssh sshd ssh-keygen python3 timeout kill mktemp; do command -v "$x" >/dev/null || { echo "SKIP: missing $x"; exit 77; }; done
BASE=$(mktemp -d -p "${TMPDIR:-/tmp}" 0035-ssh-disconnect-XXXXXXXX)
# sshd checks AuthorizedKeysFile as the target account, not root.
# Permit traversal of this disposable directory, without exposing private keys.
chmod 711 "$BASE"
SSHD_PID=''
cleanup(){ set +e; [[ -n "$SSHD_PID" ]] && kill "$SSHD_PID" 2>/dev/null; [[ -n "$CLIENT_PID" ]] && kill "$CLIENT_PID" 2>/dev/null; rm -rf -- "$BASE"; }
trap cleanup EXIT
CLIENT_PID=''
# Use a nonprivileged local account for authentication; test daemon binds only to 127.0.0.1.
ACCOUNT=${SUDO_USER:-$(id -un)}
[[ "$ACCOUNT" != root ]] || { echo 'SKIP: run via sudo from non-root local account'; exit 77; }
USER_HOME=$(getent passwd "$ACCOUNT" | cut -d: -f6)
[[ -d "$USER_HOME" ]] || { echo 'SKIP: missing test account home'; exit 77; }
ssh-keygen -q -t ed25519 -N '' -f "$BASE/id" >/dev/null
cp "$BASE/id.pub" "$BASE/authorized_keys"
chown "$ACCOUNT" "$BASE/authorized_keys"
chmod 600 "$BASE/authorized_keys"
ssh-keygen -q -t ed25519 -N '' -f "$BASE/hostkey" >/dev/null
# Find unoccupied high port on localhost; possible race causes fail closed.
PORT=$(python3 - <<'PY'
import socket
s=socket.socket();s.bind(('127.0.0.1',0));print(s.getsockname()[1]);s.close()
PY
)
cat > "$BASE/sshd_config" <<CFG
Port $PORT
ListenAddress 127.0.0.1
HostKey $BASE/hostkey
PidFile $BASE/sshd.pid
AuthorizedKeysFile $BASE/authorized_keys
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
StrictModes no
UsePAM no
AllowUsers $ACCOUNT
LogLevel ERROR
Subsystem sftp internal-sftp
CFG
mkdir -p /run/sshd
/usr/sbin/sshd -f "$BASE/sshd_config" -E "$BASE/sshd.log" || { cat "$BASE/sshd.log"; exit 1; }
SSHD_PID=$(cat "$BASE/sshd.pid")
# SSH stream whose end/ack would only occur after completion. Stop client mid-stream.
ssh -F /dev/null -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=5 -i "$BASE/id" -p "$PORT" "$ACCOUNT@127.0.0.1" 'sleep 30; echo ACCEPTED' >"$BASE/ack" 2>"$BASE/ssh.err" &
CLIENT_PID=$!
sleep 2
if ! kill -0 "$CLIENT_PID" 2>/dev/null; then echo 'FAIL: SSH client exited before interruption'; cat "$BASE/ssh.err"; cat "$BASE/sshd.log"; exit 1; fi
kill -KILL "$CLIENT_PID"
wait "$CLIENT_PID" 2>/dev/null && { echo 'FAIL: killed SSH returned success'; exit 1; } || true
CLIENT_PID=''
[[ ! -s "$BASE/ack" ]] || { echo 'FAIL: acknowledgement present after disconnect'; exit 1; }
echo 'PASS: actual loopback SSH client disconnected before receiver acknowledgement'
# This proves transport interruption only; pin safety is separately covered by source-code harness.
echo 'NOT TESTED: production sender pin lifecycle over this real SSH daemon; use offline transport regression for pin policy'
echo 'GATE B2 isolated real SSH disconnect PASS'
