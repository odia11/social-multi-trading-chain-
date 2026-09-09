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
apt-get install -y -qq python3 python3-venv python3-pip nginx sqlite3 curl ca-certificates rsync

say "Creating the service user (no login shell — it only runs the app)"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

say "Installing the application into $APP_DIR"
mkdir -p "$APP_DIR"
# --delete keeps the deployed copy exactly matching the repo, but never
# reaches into $DATA_DIR, which lives outside $APP_DIR precisely so that
# redeploying can't touch the database.
# 'venv' is excluded for a reason that cost an outage: a virtualenv records
# the ABSOLUTE path of its own python inside every script it installs. Copying
# one built in ~/orcagent into /opt/orcagent leaves gunicorn starting with
#     #!/home/<you>/orcagent/venv/bin/python3
# and the service user cannot read another user's home, so it fails to exec
# with "Permission denied" on a file that looks perfectly executable.
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '.git' --exclude '__pycache__' --exclude '*.db' \
        --exclude 'venv' "$REPO_DIR"/ "$APP_DIR"/
else
  # Without rsync there is no --delete, so removed files linger. Worth knowing
  # rather than silently getting a different deploy.
  echo "  rsync not installed — copying without --delete (stale files will remain)"
  find "$REPO_DIR" -mindepth 1 -maxdepth 1 \
       ! -name .git ! -name venv ! -name '__pycache__' \
       -exec cp -r {} "$APP_DIR"/ \;
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

say "Creating the data directory ($DATA_DIR)"
# The app writes its database, logs, backups and heartbeat here. It picks
# /data automatically when it exists (see _DATA_DIR in dashboard.py), which
# is what keeps your data outside the deployed code.
mkdir -p "$DATA_DIR/backups"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"

say "Building the Python environment"
# A venv whose scripts point somewhere else is worse than no venv: it looks
# installed and fails at exec time with a permissions error that says nothing
# about the real cause. `python3 -m venv` on an existing directory does NOT
# rewrite those paths, so the only reliable repair is to rebuild it.
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

# Checked, not assumed. This is the exact failure that took the site down.
# The output is CAPTURED rather than discarded: a check that fails without
# saying why just moves the guesswork one step later, which is the whole
# problem it exists to solve.
if ! VENV_ERR="$(sudo -u "$APP_USER" "$APP_DIR/venv/bin/gunicorn" --version 2>&1)"; then
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
# Readable only by root and the service user: this file holds the encryption
# key that every stored wallet key depends on.
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "Installing the systemd services"
cp "$REPO_DIR/deploy/orcagent.service"         /etc/systemd/system/orcagent.service
cp "$REPO_DIR/deploy/orcagent-monitor.service" /etc/systemd/system/orcagent-monitor.service
systemctl daemon-reload
systemctl enable orcagent orcagent-monitor >/dev/null

say "Installing the nginx site"
NGINX_SITE=/etc/nginx/sites-available/orcagent
# certbot rewrites this file IN PLACE to add the certificate and the HTTPS
# redirect. Copying the template over it would throw all of that away and
# reload nginx serving plain HTTP -- on a site whose session cookie is Secure,
# that means nobody can log in. So once a certificate is in there, the file
# belongs to certbot and this script leaves it alone.
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

Then point your domain at this server and run:
         certbot --nginx -d orcagent.fun -d www.orcagent.fun
────────────────────────────────────────────────────────────
EOF
