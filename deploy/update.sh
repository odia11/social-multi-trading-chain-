#!/usr/bin/env bash
# ── OrcAgent — deploy the current code ──
#
#     sudo bash ~/orcagent/deploy/update.sh
#
# One command instead of four, because the person running it is usually doing
# it from a phone. It backs the database up, pulls, reinstalls, restarts, and
# then checks the site actually came back -- and tells you how to undo it if
# it did not.
#
# Every step is ordered so that stopping partway leaves the site running on
# the old code rather than half-way onto the new.
set -euo pipefail

APP_DIR=/opt/orcagent
DATA_DIR=/data
DB="$DATA_DIR/orcagent.db"
STAMP="$(date +%F-%H%M%S)"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say(){ printf '\n\033[1;33m▸ %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this with sudo."
[ -f "$REPO_DIR/dashboard.py" ] || die "Run this from your git clone, not from $APP_DIR."

# ── 1. a backup you could actually restore from ──
# Taken with .backup rather than cp: a plain copy of a database that is being
# written to can be a file that no longer opens.
say "Backing up the database"
if [ -f "$DB" ]; then
  BACKUP="$DATA_DIR/backups/pre-deploy-$STAMP.db"
  mkdir -p "$DATA_DIR/backups"
  sqlite3 "$DB" ".backup '$BACKUP'"
  # A backup nobody has opened is a guess. This is the whole reason to take
  # one before touching anything.
  sqlite3 "$BACKUP" 'PRAGMA integrity_check;' | grep -qx ok \
    || die "The backup did not verify. Nothing has been changed. Investigate before deploying."
  USERS=$(sqlite3 "$BACKUP" 'SELECT COUNT(*) FROM users;' 2>/dev/null || echo '?')
  echo "  $BACKUP  ($(du -h "$BACKUP" | cut -f1), $USERS users) — verified"
else
  echo "  no database at $DB yet — nothing to back up"
fi

# ── 2. the code ──
say "Fetching the latest code"
BEFORE="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
git -C "$REPO_DIR" pull --ff-only
AFTER="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "  already at $AFTER — nothing new"
else
  echo "  $BEFORE -> $AFTER"
  git -C "$REPO_DIR" log --oneline "$BEFORE..$AFTER" | head -20 | sed 's/^/    /'
fi

say "Installing"
bash "$REPO_DIR/deploy/install.sh" >/tmp/orcagent-install-$STAMP.log 2>&1 \
  || { tail -30 /tmp/orcagent-install-$STAMP.log; die "Install failed. The old code is still running — nothing was restarted."; }
echo "  done (full log: /tmp/orcagent-install-$STAMP.log)"

# ── 3. restart, then prove it came back ──
say "Restarting"
# NOT under `set -e`. When systemctl restart failed, the script died on this
# line -- before the block below that prints the journal and the rollback
# commands. The one moment those are worth having is the moment they were
# skipped, so the failure is captured and handled rather than fatal.
RESTART_OK=1
systemctl restart orcagent orcagent-monitor || RESTART_OK=0

if [ "$RESTART_OK" = "1" ]; then
  printf '  waiting for the app to answer'
  for i in $(seq 1 30); do
    if curl -fsS --max-time 3 localhost:8080/health >/dev/null 2>&1; then
      printf '\n  it answers\n'
      HEALTHY=1
      break
    fi
    printf '.'
    sleep 2
  done
else
  echo "  systemctl could not start it"
fi

if [ "${HEALTHY:-0}" != "1" ]; then
  printf '\n'
  journalctl -u orcagent -n 40 --no-pager
  cat <<ROLLBACK

────────────────────────────────────────────────────────────
The app did not come back. The log above says why -- usually a
missing variable in /etc/orcagent.env, or a syntax error.

A "Permission denied" on venv/bin/gunicorn is almost never the file's
own permissions -- check what its first line points at:

    head -1 $APP_DIR/venv/bin/gunicorn

If that path is not inside $APP_DIR, the virtualenv was copied from
somewhere else and keeps the old absolute path. Rebuild it:

    sudo rm -rf $APP_DIR/venv
    sudo bash $REPO_DIR/deploy/install.sh

To go back to the code that was working instead:

    cd $REPO_DIR && sudo git checkout $BEFORE
    sudo bash deploy/install.sh
    sudo systemctl restart orcagent

Your database was NOT touched by this script, and there is a
verified copy at:
    ${BACKUP:-(none taken)}
────────────────────────────────────────────────────────────
ROLLBACK
  exit 1
fi

# ── 4. can it still reach the outside world? ──
say "Checking the services the app trades through"
set +e
( set -a; . /etc/orcagent.env; set +a
  cd "$APP_DIR" && PYTHONDONTWRITEBYTECODE=1 venv/bin/python tools/verify_live.py )
VERIFY=$?
set -e

say "Storage"
journalctl -u orcagent -n 200 --no-pager | grep -m1 '\[startup\] storage' || true

if [ $VERIFY -ne 0 ]; then
  cat <<'WARN'

The site is up, but something it trades through is not reachable -- see the
FAILED lines above. Trades that depend on it will fail for a real user.
WARN
  exit 1
fi

printf '\n\033[1;32m✓ Deployed and verified.\033[0m\n'
