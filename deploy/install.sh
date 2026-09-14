#!/usr/bin/env bash
# ── OrcAgent — one-shot server setup (Ubuntu/Debian) ──
#
# Run this ONCE on a fresh server, as root, from the repo directory:
#     sudo bash deploy/install.sh
#
# It is safe to run again: every step checks before it acts, so a re-run
# repairs a half-finished setup instead of duplicating it.
#
# What it does NOT do, on purpose:
#   - It never writes your secrets. It creates /etc/orcagent.env from the
#     template with placeholder values and stops; you fill it in yourself.
#   - It never touches an existing database. Your live data is copied over
#     separately (see deploy/README.md) so a mistake here cannot erase it.
set -euo pipefail

APP_USER=orcagent
APP_DIR=/opt/orcagent
DATA_DIR=/data
ENV_FILE=/etc/orcagent.env
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say(){ printf '\n\033[1;33m▸ %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || { echo "Run this with sudo."; exit 1; }

say "Installing system packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx sqlite3 curl ca-certificates rsync openssl

say "Creating the service user (no login shell — it only runs the app)"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

say "Installing the application into $APP_DIR"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '.git' --exclude '__pycache__' --exclude '*.db' \
        --exclude 'venv' --exclude '.secret_key' "$REPO_DIR"/ "$APP_DIR"/

  if [ -e "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" rev-parse --short HEAD > "$APP_DIR/VERSION" 2>/dev/null || true
  fi
else
  echo "  rsync not installed — copying without --delete (stale files will remain)"
  find "$REPO_DIR" -mindepth 1 -maxdepth 1 \
       ! -name .git ! -name venv ! -name '__pycache__' \
       -exec cp -r {} "$APP_DIR"/ \;
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

say "Creating the data directory ($DATA_DIR)"
mkdir -p "$DATA_DIR/backups"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"

say "Building the Python environment"
if [ -x "$APP_DIR/venv/bin/gunicorn" ] \
   && ! head -1 "$APP_DIR/venv/bin/gunicorn" | grep -q "^#\!$APP_DIR/"; then
  echo "  existing venv points outside $APP_DIR ($(head -1 "$APP_DIR/venv/bin/gunicorn"))"
  echo "  rebuilding it"
  rm -rf "$APP_DIR/venv"
fi
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --quiet --upgrade pip
"$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/venv"

if ! VENV_ERR="$(cd "$APP_DIR" && sudo -u "$APP_USER" "$APP_DIR/venv/bin/gunicorn" --version 2>&1)"; then
  printf '\n\033[1;31m✗ The service user cannot run %s\033[0m\n' "$APP_DIR/venv/bin/gunicorn"
  echo "  it said: $VENV_ERR"
  echo "  its interpreter line: $(head -1 "$APP_DIR/venv/bin/gunicorn")"
  echo "  interpreter present:  $(ls -l "$APP_DIR/venv/bin/python3" 2>&1)"
  echo "  directory:            $(ls -ld "$APP_DIR" "$APP_DIR/venv" 2>&1 | tr '\n' ' ')"
  exit 1
fi
echo "  $("$APP_DIR/venv/bin/gunicorn" --version) — runnable by $APP_USER"

say "Preparing the environment file ($ENV_FILE)"
if [ -f "$ENV_FILE" ]; then
  echo "  already exists — left untouched so your secrets are not overwritten"
else
  cp "$REPO_DIR/deploy/env.example" "$ENV_FILE"
  echo "  created from the template — FILL IT IN before starting the service"
fi
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "Installing the systemd services"
cp "$REPO_DIR/deploy/orcagent.service"           /etc/systemd/system/orcagent.service
cp "$REPO_DIR/deploy/orcagent-monitor.service"   /etc/systemd/system/orcagent-monitor.service
cp "$REPO_DIR/deploy/orcagent-backup.service"    /etc/systemd/system/orcagent-backup.service
cp "$REPO_DIR/deploy/orcagent-backup.timer"      /etc/systemd/system/orcagent-backup.timer
chmod 755 "$APP_DIR/deploy/backup.sh"

# Fail before restarting production if a security directive is misspelled or
# a unit is otherwise invalid. This prevents a hardening change from turning
# into an outage on deploy.
if ! systemd-analyze verify \
    /etc/systemd/system/orcagent.service \
    /etc/systemd/system/orcagent-monitor.service \
    /etc/systemd/system/orcagent-backup.service \
    /etc/systemd/system/orcagent-backup.timer >/tmp/orcagent-systemd-verify.log 2>&1; then
  cat /tmp/orcagent-systemd-verify.log
  die "systemd unit verification failed — production was not restarted"
fi
echo "  systemd unit verification passed"

systemctl daemon-reload
systemctl enable orcagent orcagent-monitor >/dev/null
systemctl enable --now orcagent-backup.timer >/dev/null

say "Verifying backup protection"
if ! systemctl is-enabled --quiet orcagent-backup.timer; then
  die "orcagent-backup.timer is not enabled"
fi
if ! systemctl is-active --quiet orcagent-backup.timer; then
  die "orcagent-backup.timer is not active"
fi

# Prove the unprivileged, sandboxed backup can really read the DB and secret
# and create a restore-verified encrypted artifact. If there is no DB yet the
# script exits cleanly and the fresh-install path remains valid.
if ! systemctl start orcagent-backup.service; then
  journalctl -u orcagent-backup.service -n 40 --no-pager || true
  die "encrypted backup service failed its execution test"
fi
if [ -f "$DATA_DIR/orcagent.db" ]; then
  LATEST_BACKUP="$(ls -1t "$DATA_DIR"/backups/daily/orcagent-*.db.gz.enc 2>/dev/null | head -1 || true)"
  [ -n "$LATEST_BACKUP" ] || die "backup service ran but produced no encrypted backup"
  echo "  verified encrypted backup: $LATEST_BACKUP"
fi
NEXT_BACKUP="$(systemctl list-timers orcagent-backup.timer --no-legend 2>/dev/null | awk '{print $1" "$2" "$3" "$4}' || true)"
echo "  daily backup timer active${NEXT_BACKUP:+ — next: $NEXT_BACKUP}"

say "Installing the nginx site"
NGINX_SITE=/etc/nginx/sites-available/orcagent
if [ -f "$NGINX_SITE" ] && grep -q 'ssl_certificate' "$NGINX_SITE"; then
  echo "  already has a certificate — left untouched so certbot's config survives"
  echo "  (if you need the template back: certbot delete, then re-run this)"
else
  cp "$REPO_DIR/deploy/nginx-orcagent.conf" "$NGINX_SITE"
  echo "  installed (plain HTTP — run certbot afterwards)"
fi
ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/orcagent
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

cat <<EOF

────────────────────────────────────────────────────────────
Setup complete. Three things left, in this order:

  1. Fill in your secrets:
         nano $ENV_FILE

     ENCRYPTION_KEY must be EXACTLY the value from Railway.
     A different key makes every stored wallet key unreadable.

  2. Copy your live database across (see deploy/README.md),
     otherwise the app starts empty — no users, no trades.

  3. Start it:
         systemctl start orcagent orcagent-monitor
         systemctl status orcagent
         journalctl -u orcagent -f

The encrypted verified database backup timer is installed and enabled too.
You can check it with:
         systemctl status orcagent-backup.timer
         systemctl list-timers orcagent-backup.timer

Then point your domain at this server and run:
         certbot --nginx -d orcagent.fun -d www.orcagent.fun
────────────────────────────────────────────────────────────
EOF
