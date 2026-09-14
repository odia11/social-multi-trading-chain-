#!/usr/bin/env bash
# Post-deploy security smoke test. Read-only: it checks the running process and
# response headers, never signs or submits a transaction.
set -euo pipefail

fail(){ printf 'FAIL %s\n' "$*" >&2; exit 1; }
ok(){ printf '  OK  %s\n' "$*"; }

BASE=http://127.0.0.1:8080
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

for _ in $(seq 1 15); do
  if curl -fsS -D "$TMP" -o /dev/null --max-time 4 "$BASE/"; then
    break
  fi
  sleep 1
done
[ -s "$TMP" ] || fail "app root is not reachable"

header(){
  awk -v n="$1" 'BEGIN{IGNORECASE=1} $0 ~ "^" n ":" {sub(/^[^:]+:[[:space:]]*/,""); sub(/\r$/,""); print; exit}' "$TMP"
}

[ "$(header X-Content-Type-Options)" = "nosniff" ] || fail "X-Content-Type-Options=nosniff missing"
ok "MIME sniffing disabled"

[ "$(header X-Frame-Options)" = "DENY" ] || fail "X-Frame-Options=DENY missing"
ok "legacy framing denied"

CSP="$(header Content-Security-Policy)"
[ -n "$CSP" ] || fail "Content-Security-Policy missing"
printf '%s' "$CSP" | grep -q "object-src 'none'" || fail "CSP does not disable object-src"
printf '%s' "$CSP" | grep -q "frame-ancestors 'none'" || fail "CSP does not deny frame ancestors"
printf '%s' "$CSP" | grep -q "script-src-elem.*nonce-" || fail "CSP nonce for script elements missing"
ok "nonce-gated CSP present"

COOKIE="$(grep -i '^Set-Cookie:' "$TMP" | head -1 || true)"
if [ -n "$COOKIE" ]; then
  printf '%s' "$COOKIE" | grep -qi 'HttpOnly' || fail "session cookie is not HttpOnly"
  printf '%s' "$COOKIE" | grep -qi 'Secure' || fail "session cookie is not Secure"
  printf '%s' "$COOKIE" | grep -qi 'SameSite=Lax' || fail "session cookie SameSite policy missing"
  ok "session cookie attributes hardened"
fi

if command -v ss >/dev/null 2>&1; then
  LISTEN="$(ss -ltnH '( sport = :8080 )' 2>/dev/null || true)"
  [ -n "$LISTEN" ] || fail "nothing is listening on app port 8080"
  printf '%s\n' "$LISTEN" | grep -Eq '127\.0\.0\.1:8080|\[::1\]:8080' \
    || fail "app port 8080 is not loopback-only"
  if printf '%s\n' "$LISTEN" | grep -Eq '(^|[[:space:]])0\.0\.0\.0:8080|\[::\]:8080'; then
    fail "gunicorn port 8080 is publicly bound"
  fi
  ok "gunicorn bound to loopback only"
fi

SHELL_PATH="$(getent passwd orcagent | cut -d: -f7 || true)"
case "$SHELL_PATH" in
  */nologin|*/false) ok "service account has no login shell" ;;
  *) fail "orcagent service account has an interactive shell: $SHELL_PATH" ;;
esac

MODE="$(stat -c '%a' /etc/orcagent.env 2>/dev/null || true)"
[ "$MODE" = "640" ] || [ "$MODE" = "600" ] || fail "/etc/orcagent.env permissions are $MODE (expected 640/600)"
ok "production environment file is not world-readable"

# Persistent application state can contain wallet/session records and audit
# information. Nothing under /data should be group/world readable or writable.
DATA_MODE="$(stat -c '%a' /data 2>/dev/null || true)"
[ "$DATA_MODE" = "700" ] || fail "/data permissions are $DATA_MODE (expected 700)"
if find /data -xdev \( -type f -o -type d \) \( -perm /0077 \) -print -quit 2>/dev/null | grep -q .; then
  BAD_PATH="$(find /data -xdev \( -type f -o -type d \) \( -perm /0077 \) -print -quit 2>/dev/null || true)"
  fail "persistent state is accessible to group/world: $BAD_PATH"
fi
if [ -f /data/orcagent.db ]; then
  DB_MODE="$(stat -c '%a' /data/orcagent.db)"
  [ "$DB_MODE" = "600" ] || fail "database permissions are $DB_MODE (expected 600)"
fi
ok "persistent application state is owner-only"

STATE="$(systemctl is-active orcagent 2>/dev/null || true)"
case "$STATE" in active|activating) ;; *) fail "orcagent service state is $STATE" ;; esac
systemctl is-active --quiet orcagent-backup.timer || fail "backup timer is not active"
ok "app and encrypted-backup timer active"

printf '\nSecurity smoke checks passed.\n'
