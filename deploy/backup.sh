#!/usr/bin/env bash
# Encrypted, verified OrcAgent database backup. Safe to run while SQLite is live.
set -euo pipefail
DB=/data/orcagent.db
OUT=/data/backups/daily
ENV=/etc/orcagent.env
[ -f "$DB" ] || exit 0
[ -r "$ENV" ] || { echo "backup: $ENV is not readable" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
. "$ENV"
set +a
[ -n "${SECRET_KEY:-}" ] || { echo "backup: SECRET_KEY is required" >&2; exit 1; }
command -v sqlite3 >/dev/null
command -v openssl >/dev/null
mkdir -p "$OUT"
umask 077
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TMP="$(mktemp /data/backups/.orcagent-backup.XXXXXX.db)"
GZ="$TMP.gz"
ENC="$OUT/orcagent-$STAMP.db.gz.enc"
RESTORE="$(mktemp /data/backups/.orcagent-restore.XXXXXX.db)"
cleanup(){ rm -f "$TMP" "$GZ" "$RESTORE" "$RESTORE.gz"; }
trap cleanup EXIT

sqlite3 "$DB" ".backup '$TMP'"
sqlite3 "$TMP" 'PRAGMA integrity_check;' | grep -qx ok
# Domain-separated backup passphrase derived from the session secret without
# writing either the source secret or derived passphrase to disk.
BACKUP_KEY="$(printf 'orcagent-backup-v1:%s' "$SECRET_KEY" | sha256sum | awk '{print $1}')"
gzip -9 "$TMP"
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
  -in "$GZ" -out "$ENC" -pass env:BACKUP_KEY
chmod 600 "$ENC"

# A backup is not trusted until the exact encrypted artifact can be restored.
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -in "$ENC" -out "$RESTORE.gz" -pass env:BACKUP_KEY
gunzip -f "$RESTORE.gz"
sqlite3 "$RESTORE" 'PRAGMA integrity_check;' | grep -qx ok

# Retain 14 daily restore points.
ls -1t "$OUT"/orcagent-*.db.gz.enc 2>/dev/null | tail -n +15 | xargs -r rm -f
printf 'backup: verified encrypted backup %s\n' "$ENC"
