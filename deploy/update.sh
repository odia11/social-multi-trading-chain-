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
die(){ EXPLAINED=1; printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

# `set -e` is right for a deploy script -- stopping early leaves the site on
# the old code -- but on its own it stops SILENTLY, and this has now twice
# ended with a bare prompt and no clue which line gave up. Every deliberate
# exit sets EXPLAINED, so this only speaks when nothing else did.
EXPLAINED=0
FAILED_LINE=''
PULLED=0
trap 'FAILED_LINE=$LINENO' ERR
trap '_rc=$?
      if [ "$_rc" -ne 0 ] && [ "$EXPLAINED" != 1 ]; then
        printf "\n\033[1;31m✗ Stopped at line %s (exit %s), and not on purpose.\033[0m\n" \
               "${FAILED_LINE:-?}" "$_rc"
        printf "  Nothing after that line ran. Your database was not touched and\n"
        printf "  the site is still on the code it was already running.\n"
        # The trap that matters most. Everything before "Fetching the latest
        # code" runs from the copy of this script already on disk, so a bug
        # in it cannot be fixed by running it again -- the fix is sitting in
        # the repository on the other side of a pull that never happens.
        # Breaking that deadlock by hand is two commands, and nobody should
        # have to work them out at the prompt.
        if [ "$PULLED" != 1 ]; then
          printf "\n  This stopped BEFORE the pull, so a newer version of this script\n"
          printf "  cannot reach you by running it again. Pull by hand first:\n\n"
          printf "      git -C %s pull --ff-only\n" "$REPO_DIR"
          printf "      sudo bash %s/deploy/update.sh\n" "$REPO_DIR"
        fi
      fi' EXIT

[ "$(id -u)" -eq 0 ] || die "Run this with sudo."

# This script pulls, so it has to run from the git clone. The deployed copy at
# $APP_DIR is not one: install.sh rsyncs the files across with --exclude '.git'.
#
# The check used to be for dashboard.py, which install.sh copies -- so running
# it from $APP_DIR passed the guard and then died several steps later on
# "fatal: not a git repository", after the backup had already been taken. The
# thing that distinguishes a clone from a deploy is the .git directory, so
# that is what is tested.
#
# And the error hands over a command rather than a description of one: whoever
# is running this is usually on a phone, and "run it from your clone" is not
# something you can paste.
if [ ! -e "$REPO_DIR/.git" ]; then
  CLONE=""
  for c in /home/*/orcagent /root/orcagent; do
    [ -e "$c/.git" ] && [ -f "$c/deploy/update.sh" ] && { CLONE="$c"; break; }
  done
  if [ -n "$CLONE" ]; then
    die "$REPO_DIR is the deployed copy, not the git clone — it has no .git to pull into.

    Run this instead:

        sudo bash $CLONE/deploy/update.sh"
  fi
  die "$REPO_DIR is not a git clone (no .git), and none was found in a home
    directory. Clone the repository first, then run deploy/update.sh from it."
fi

# ── git runs as the clone's owner, never as root ──
#
# This script needs sudo (systemctl, /opt, /data) but git MUST NOT inherit it.
# A `git pull` run as root writes root-owned files into .git/objects, and from
# then on the person who owns the clone cannot pull at all:
#
#     error: insufficient permission for adding an object to repository
#     database .git/objects
#
# Which is exactly what happened: the deploy pulled as root, and every later
# `git pull` from the normal account failed. The repository was left in a
# state only sudo could write to -- caused entirely by this script.
#
# So: work out who owns the clone and drop back to them for anything git.
REPO_OWNER="$(stat -c '%U' "$REPO_DIR/.git" 2>/dev/null || echo root)"
REPO_GROUP="$(stat -c '%G' "$REPO_DIR/.git" 2>/dev/null || echo root)"
git_repo(){
  if [ "$REPO_OWNER" != root ] && id -u "$REPO_OWNER" >/dev/null 2>&1; then
    runuser -u "$REPO_OWNER" -- git -C "$REPO_DIR" "$@"
  else
    git -C "$REPO_DIR" "$@"
  fi
}

# And repair the damage already done, rather than only stopping it recurring.
# Anyone whose clone was poisoned by an earlier version of this script is
# locked out of pulling the version that fixes it, so the fix has to be able
# to run without their help. Cheap: -quit stops at the first hit.
if [ "$REPO_OWNER" != root ] && [ -n "$(find "$REPO_DIR/.git" -user root -print -quit 2>/dev/null)" ]; then
  say "Repairing repository ownership"
  echo "  parts of $REPO_DIR/.git are owned by root — an earlier deploy pulled"
  echo "  as root. Giving them back to $REPO_OWNER so you can pull normally."
  chown -R "$REPO_OWNER:$REPO_GROUP" "$REPO_DIR/.git"
fi

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
  RAW=$(du -h "$BACKUP" | cut -f1)

  # Compressed only AFTER it has been verified, so the check runs on something
  # sqlite can open. A database of mostly text and base64 images compresses to
  # roughly a third, which is what the app's own backups have always done --
  # these were the only ones left sitting there at full size.
  gzip -f "$BACKUP" && BACKUP="$BACKUP.gz"
  echo "  $BACKUP  ($RAW -> $(du -h "$BACKUP" | cut -f1), $USERS users) — verified"

  # Keep the last few and delete the rest. The app prunes its OWN backups,
  # but it matches them by an 'orcagent_' prefix, so these are invisible to
  # it -- they would sit there growing by one database per deploy until the
  # volume filled, which is exactly how the last disk problem started.
  # Both shapes: the compressed ones written now, and any plain .db left by
  # an earlier version of this script.
  #
  # The `|| true` is not decoration. `ls a* b*` exits non-zero when EITHER
  # pattern matches nothing, `set -o pipefail` promotes that to the whole
  # pipeline, and `set -e` then kills the script -- with 2>/dev/null hiding
  # the reason, so the deploy simply stopped after the backup and said
  # nothing at all.
  #
  # Gzipping these is what armed it: while one plain .db was still lying
  # around the first pattern matched and ls exited 0. The run that deleted
  # the last plain one left only .gz files, and every deploy after it died
  # here. A bug that appears two deploys after the change that caused it.
  #
  # More generally: pruning old backups is housekeeping. It must not be able
  # to stop a deploy, whatever it runs into.
  KEEP=3
  OLD_BACKUPS="$(ls -1t "$DATA_DIR"/backups/pre-deploy-*.db \
                          "$DATA_DIR"/backups/pre-deploy-*.db.gz 2>/dev/null \
                 | tail -n +$((KEEP + 1)) || true)"
  if [ -n "$OLD_BACKUPS" ]; then
    printf '%s\n' "$OLD_BACKUPS" | while read -r old_backup; do
      rm -f "$old_backup" && echo "  removed old $(basename "$old_backup")"
    done
  fi
else
  echo "  no database at $DB yet — nothing to back up"
fi

# ── 2. the code ──
say "Fetching the latest code"
BEFORE="$(git_repo rev-parse --short HEAD 2>/dev/null || echo unknown)"
git_repo pull --ff-only
AFTER="$(git_repo rev-parse --short HEAD 2>/dev/null || echo unknown)"
if [ "$BEFORE" = "$AFTER" ]; then
  echo "  already at $AFTER — nothing new"
else
  echo "  $BEFORE -> $AFTER"
  git_repo log --oneline "$BEFORE..$AFTER" | head -20 | sed 's/^/    /'
fi

PULLED=1

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

    git -C $REPO_DIR checkout $BEFORE
        ^ without sudo: a git command run as root leaves root-owned
          directories under .git and you will not be able to pull again.
    sudo bash $REPO_DIR/deploy/install.sh
    sudo systemctl restart orcagent

Your database was NOT touched by this script, and there is a
verified copy at:
    ${BACKUP:-(none taken)}

To restore it:
    sudo systemctl stop orcagent
    sudo gunzip -c ${BACKUP:-BACKUP} > /data/orcagent.db
    sudo chown orcagent:orcagent /data/orcagent.db
    sudo systemctl start orcagent
────────────────────────────────────────────────────────────
ROLLBACK
  EXPLAINED=1
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
  EXPLAINED=1
  exit 1
fi

EXPLAINED=1
printf '\n\033[1;32m✓ Deployed and verified.\033[0m\n'
