#!/usr/bin/env bash
# Apply OrcAgent static-asset performance settings without replacing the
# Certbot-managed nginx site. Safe to run after every deploy.
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run this with sudo."; exit 1; }
SITE=/etc/nginx/sites-available/orcagent
[ -f "$SITE" ] || { echo "nginx site not found at $SITE"; exit 1; }

python3 - "$SITE" <<'PY'
import re, sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()

# Only touch the existing /static/ location; Certbot's SSL directives,
# redirects and certificates are deliberately outside this match.
pat = re.compile(r"location\s+/static/\s*\{.*?\n\s*\}", re.S)
m = pat.search(text)
if not m:
    raise SystemExit('Could not find location /static/ in nginx site; left it untouched.')

block = m.group(0)
if 'stale-while-revalidate=86400' in block and 'gzip_types' in block:
    print('  nginx static performance settings already present')
    raise SystemExit(0)

indent = re.match(r'(\s*)location', block).group(1)
i = indent + '    '
new = (
    indent + 'location /static/ {\n'
    + i + 'alias /opt/orcagent/static/;\n'
    + i + 'etag on;\n'
    + i + 'expires 7d;\n'
    + i + 'add_header Cache-Control "public, max-age=604800, stale-while-revalidate=86400" always;\n'
    + i + 'gzip on;\n'
    + i + 'gzip_vary on;\n'
    + i + 'gzip_min_length 1024;\n'
    + i + 'gzip_comp_level 5;\n'
    + i + 'gzip_types text/plain text/css application/javascript application/json application/manifest+json image/svg+xml;\n'
    + i + 'open_file_cache max=2000 inactive=60s;\n'
    + i + 'open_file_cache_valid 120s;\n'
    + i + 'open_file_cache_min_uses 2;\n'
    + i + 'open_file_cache_errors on;\n'
    + i + 'access_log off;\n'
    + indent + '}'
)
path.write_text(text[:m.start()] + new + text[m.end():])
print('  patched nginx /static/ location; Certbot SSL config preserved')
PY

nginx -t
systemctl reload nginx
echo "  nginx reloaded"
