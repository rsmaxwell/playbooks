#!/usr/bin/env bash
# 0036 Step 3: disposable real pg_dump integration gate.
# No connections, volumes, ports, or credentials from the production Diaries stack.
set -Eeuo pipefail

image="${1:-postgres:18-alpine}"
command -v docker >/dev/null || { echo 'BLOCKED: docker unavailable' >&2; exit 2; }
docker compose version >/dev/null || { echo 'BLOCKED: docker compose plugin unavailable' >&2; exit 2; }

work="$(mktemp -d -t diaries-0036-pgdump-XXXXXXXX)"
project="diaries0036pg${RANDOM}${RANDOM}"
compose="$work/compose.yaml"
cleanup() {
  docker compose -p "$project" -f "$compose" down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$work"
}
trap cleanup EXIT

# The container's database is entirely disposable. No host ports or shared mounts.
cat > "$compose" <<YAML
services:
  postgres:
    image: ${image}
    environment:
      POSTGRES_USER: rehearsal
      POSTGRES_PASSWORD: disposable-only
      POSTGRES_DB: diaries0036test
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U rehearsal -d diaries0036test"]
      interval: 2s
      timeout: 3s
      retries: 30
YAML

# Fixed image passed as a single argument; reject accidental Compose variable interpolation.
if [[ "$image" == *'$'* || "$image" == *$'\n'* || "$image" == *$'\r'* ]]; then
  echo 'FAIL: invalid image argument' >&2; exit 1
fi

dc=(docker compose -p "$project" -f "$compose")
"${dc[@]}" up -d --wait --wait-timeout 90 >/dev/null
"${dc[@]}" exec -T postgres psql -v ON_ERROR_STOP=1 --username rehearsal --dbname diaries0036test <<'SQL'
CREATE TABLE diary_probe (id integer PRIMARY KEY, title text NOT NULL);
INSERT INTO diary_probe VALUES (1, '0036 real dump verification'), (2, 'round-trip restored');
SQL

# These options and the exec -T mechanism match fixed-dataset-capture.py.
"${dc[@]}" exec -T postgres pg_dump --format=custom --no-owner --no-privileges \
  --username rehearsal --dbname diaries0036test > "$work/diaries.dump"
"${dc[@]}" exec -T postgres pg_dump --format=plain --no-owner --no-privileges \
  --username rehearsal --dbname diaries0036test > "$work/diaries.sql"

test -s "$work/diaries.dump"
test -s "$work/diaries.sql"
"${dc[@]}" exec -T postgres pg_restore --list < "$work/diaries.dump" > "$work/restore-list.txt"
grep -q 'diary_probe' "$work/restore-list.txt"
grep -q 'PostgreSQL database dump' "$work/diaries.sql"
grep -q 'PostgreSQL database dump complete' "$work/diaries.sql"

"${dc[@]}" exec -T postgres createdb --username rehearsal diaries0036restored
"${dc[@]}" exec -T postgres pg_restore --exit-on-error --no-owner --no-privileges \
  --username rehearsal --dbname diaries0036restored < "$work/diaries.dump"
actual="$("${dc[@]}" exec -T postgres psql --username rehearsal --dbname diaries0036restored -Atc \
  'SELECT count(*) FROM diary_probe;')"
# Above query must be valid PostgreSQL SQL; count=2 means restored rows are readable.
[[ "$actual" == 2 ]] || { echo "FAIL: restored row count $actual (expected 2)" >&2; exit 1; }
printf 'PASS: real PostgreSQL 18 disposable database and actual docker compose exec -T pg_dump (custom/plain)\n'
printf 'PASS: pg_restore --list, plain SQL boundary markers, and custom dump restore with two rows\n'
printf 'PASS: isolated Compose project, no published ports, disposable Docker volume, no production paths\n'
