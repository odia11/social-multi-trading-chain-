#!/usr/bin/env bash
# ── OrcAgent — one-shot server setup (Ubuntu/Debian) ──
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
# ffmpeg: video posts are re-encoded (H.264, metadata stripped, <=720p) and
# length-checked server-side before they can be published (video_uploads.py).
apt-get install -y -qq python3 python3-venv python3-pip nginx sqlite3 curl ca-certificates rsync openssl ffmpeg

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

say "Creating and locking down the data directory ($DATA_DIR)"
mkdir -p "$DATA_DIR/backups"
chown -R "$APP_USER:$APP_USER" "$DATA_DIR"
find "$DATA_DIR" -xdev -type d -exec chmod 700 {} +
find "$DATA_DIR" -xdev -type f -exec chmod 600 {} +
chmod 700 "$DATA_DIR" "$DATA_DIR/backups"
echo "  persistent state is owner-only"

# Published video posts are PUBLIC content that nginx serves straight from
# disk, so they cannot live under the owner-only $DATA_DIR. Raw uploads (which
# may still carry location metadata) stay private under $DATA_DIR until
# ffmpeg has re-encoded them.
MEDIA_DIR=/var/lib/orcagent-media
say "Creating the public media directory ($MEDIA_DIR)"
mkdir -p "$MEDIA_DIR/videos"
chown -R "$APP_USER:$APP_USER" "$MEDIA_DIR"
chmod 755 "$MEDIA_DIR" "$MEDIA_DIR/videos"
find "$MEDIA_DIR/videos" -type f -exec chmod 644 {} +

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
  echo "  already exists — secrets left untouched"
else
  cp "$REPO_DIR/deploy/env.example" "$ENV_FILE"
  echo "  created from the template — FILL IT IN before starting the service"
fi

# Product invariant: OrcAgent never advances gas for users. Preserve every
# secret/value in the production env file, but normalize this one policy flag
# on every install so an old Railway-era value cannot silently re-enable
# sponsor spending. verify_live.py sources this same file after deployment.
sed -i '/^[[:space:]]*ORCAGENT_FRONTS_GAS=/d' "$ENV_FILE"
printf '\nORCAGENT_FRONTS_GAS=0\n' >> "$ENV_FILE"
echo "  gas policy enforced: users fund their own native gas"

chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

say "Installing the systemd services"
cp "$REPO_DIR/deploy/orcagent.service"           /etc/systemd/system/orcagent.service
cp "$REPO_DIR/deploy/orcagent-monitor.service"   /etc/systemd/system/orcagent-monitor.service
cp "$REPO_DIR/deploy/orcagent-backup.service"    /etc/systemd/system/orcagent-backup.service
cp "$REPO_DIR/deploy/orcagent-backup.timer"      /etc/systemd/system/orcagent-backup.timer
chmod 755 "$APP_DIR/deploy/backup.sh" "$APP_DIR/deploy/security-smoke.sh"

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
systemctl is-enabled --quiet orcagent-backup.timer || die "orcagent-backup.timer is not enabled"
systemctl is-active --quiet orcagent-backup.timer || die "orcagent-backup.timer is not active"
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

say "Installing nginx security layer"
mkdir -p /etc/nginx/snippets /etc/nginx/conf.d
cp "$REPO_DIR/deploy/nginx-security-zones.conf" /etc/nginx/conf.d/orcagent-security-zones.conf
cp "$REPO_DIR/deploy/nginx-server-security.conf" /etc/nginx/snippets/orcagent-server-security.conf
chmod 644 /etc/nginx/conf.d/orcagent-security-zones.conf /etc/nginx/snippets/orcagent-server-security.conf

NGINX_SITE=/etc/nginx/sites-available/orcagent
if [ -f "$NGINX_SITE" ] && grep -q 'ssl_certificate' "$NGINX_SITE"; then
  echo "  existing Certbot TLS site preserved"
else
  cp "$REPO_DIR/deploy/nginx-orcagent.conf" "$NGINX_SITE"
  echo "  installed plain HTTP template — run certbot on a fresh server"
fi

if ! grep -qF 'include /etc/nginx/snippets/orcagent-server-security.conf;' "$NGINX_SITE"; then
  sed -i '/server_name[[:space:]]\+orcagent\.fun[[:space:]]\+www\.orcagent\.fun;/a\    include /etc/nginx/snippets/orcagent-server-security.conf;' "$NGINX_SITE"
fi
grep -qF 'include /etc/nginx/snippets/orcagent-server-security.conf;' "$NGINX_SITE" \
  || die "could not attach nginx security snippet to the OrcAgent server block"

# Certbot-managed production files are preserved above, so explicitly repair
# the one proxy directive that affects security identity. proxy_add_* trusts
# any X-Forwarded-For value supplied by the client and would let attackers
# evade per-IP abuse ceilings/audit attribution. OrcAgent is directly behind
# this nginx instance, so the socket peer is the authoritative client IP.
sed -Ei 's#proxy_set_header[[:space:]]+X-Forwarded-For[[:space:]]+\$proxy_add_x_forwarded_for;#proxy_set_header X-Forwarded-For   \$remote_addr;#g' "$NGINX_SITE"
if grep -q '\$proxy_add_x_forwarded_for' "$NGINX_SITE"; then
  die "unsafe X-Forwarded-For append is still present in nginx configuration"
fi

# Preserve Certbot TLS, but repair the live /static/ block on every deploy.
# Without this, older production sites keep serving the 474 KB dashboard bundle
# uncompressed even though the fresh-install template already enables gzip.
bash "$REPO_DIR/deploy/apply-nginx-performance.sh"
# Serve published video posts directly from disk (range requests, no Flask
# thread held per viewer). Idempotent, preserves Certbot's TLS config.
bash "$REPO_DIR/deploy/apply-nginx-media.sh"

ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/orcagent
rm -f /etc/nginx/sites-enabled/default
nginx -t || die "nginx security configuration failed validation"
systemctl reload nginx

NGINX_DUMP="$(nginx -T 2>/dev/null)"
printf '%s' "$NGINX_DUMP" | grep -q 'limit_conn_zone .*orca_conn' \
  || die "nginx connection-abuse zone is not loaded"
printf '%s' "$NGINX_DUMP" | grep -q 'limit_conn orca_conn 80' \
  || die "nginx OrcAgent connection limit is not active"
printf '%s' "$NGINX_DUMP" | grep -q 'server_tokens off' \
  || die "nginx server token suppression is not active"
printf '%s' "$NGINX_DUMP" | grep -q 'proxy_set_header X-Forwarded-For[[:space:]]*\$remote_addr' \
  || die "nginx is not enforcing a trusted forwarded client IP"
echo "  nginx edge hardening active"

cat <<EOF

────────────────────────────────────────────────────────────
Setup complete.

The application process is sandboxed, startup validates security headers and
loopback binding, persistent data is owner-only, nginx rejects TRACE/CONNECT,
strips spoofable forwarded IPs and limits abusive connection fan-out, and
encrypted restore-verified database backups are scheduled.

Gas policy: OrcAgent fronts nothing; every user funds network gas from their
own trading wallet.

Useful checks:
    systemctl status orcagent
    systemctl status orcagent-backup.timer
    sudo -u orcagent /opt/orcagent/deploy/security-smoke.sh

On a fresh server, fill $ENV_FILE, copy the live database, start the services,
then obtain TLS with:
    certbot --nginx -d orcagent.fun -d www.orcagent.fun
────────────────────────────────────────────────────────────
EOF
