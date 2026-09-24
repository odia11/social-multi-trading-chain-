#!/usr/bin/env bash
# Let nginx serve published video posts straight from disk. Without this the
# Flask fallback route still works, but every viewer would hold one of the
# app's four request threads for as long as a video streams.
#
# Idempotent and safe after every deploy: only inserts a location block in
# front of each existing `location /static/` block, never touching Certbot's
# TLS directives.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run this with sudo."; exit 1; }
SITE=/etc/nginx/sites-available/orcagent
[ -f "$SITE" ] || { echo "nginx site not found at $SITE"; exit 1; }

BACKUP="$(mktemp)"
cp -p "$SITE" "$BACKUP"

python3 - "$SITE" <<'PY'
import re, sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
if '/var/lib/orcagent-media/videos/' in text:
    print('  nginx video media location already present')
    raise SystemExit(0)

def block(indent):
    i = indent + '    '
    return (
        indent + 'location ~ "^/media/videos/([a-f0-9]{32}\\.(mp4|jpg))$" {\n'
        + i + 'alias /var/lib/orcagent-media/videos/$1;\n'
        + i + 'limit_except GET { deny all; }\n'
        + i + 'types { video/mp4 mp4; image/jpeg jpg; }\n'
        + i + 'default_type application/octet-stream;\n'
        + i + 'add_header Cache-Control "public, max-age=31536000, immutable" always;\n'
        + i + 'add_header X-Content-Type-Options "nosniff" always;\n'
        + i + 'add_header Referrer-Policy "strict-origin-when-cross-origin" always;\n'
        + i + 'add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;\n'
        + i + 'access_log off;\n'
        + indent + '}\n'
    )

out, last, n = [], 0, 0
for m in re.finditer(r'^([ \t]*)location\s+/static/\s*\{', text, re.M):
    out.append(text[last:m.start()])
    out.append(block(m.group(1)))
    last = m.start()
    n += 1
if not n:
    raise SystemExit('Could not find location /static/ in nginx site; left it untouched.')
out.append(text[last:])
path.write_text(''.join(out))
print(f'  added nginx video media location to {n} server block(s)')
PY

# Never leave a deploy stuck on this optional speed-up: if nginx rejects the
# new block, put the site back exactly as it was and carry on -- videos are
# then served by the app's own fallback route.
if nginx -t 2>/dev/null; then
  systemctl reload nginx
  echo "  nginx reloaded"
else
  cp -p "$BACKUP" "$SITE"
  echo "  nginx rejected the video location -- restored the previous site config;"
  echo "  videos will be served by the app instead"
fi
rm -f "$BACKUP"
