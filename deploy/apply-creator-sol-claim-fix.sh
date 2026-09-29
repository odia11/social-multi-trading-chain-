#!/usr/bin/env bash
# Guarded production deploy for the SOL Creator Fee claim RPC fix.
# Does not sign, send, approve or claim any wallet transaction.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Run with sudo." >&2; exit 1; }

SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
TARGET=/opt/orcagent
MANIFEST="$SOURCE/deploy/creator-sol-claim-manifest.json"
PYTHON="$TARGET/venv/bin/python"

"$PYTHON" - "$SOURCE" "$TARGET" "$MANIFEST" <<'PY'
import hashlib,json,sys
from pathlib import Path
source,target,manifest_path=map(Path,sys.argv[1:])
m=json.loads(manifest_path.read_text())['token_launch.py']
src=source/'token_launch.py'; dst=target/'token_launch.py'
if hashlib.sha256(src.read_bytes()).hexdigest()!=m['after']:
    raise SystemExit('STOP: reviewed source changed')
if not dst.exists():
    raise SystemExit('STOP: production token_launch.py missing')
cur=hashlib.sha256(dst.read_bytes()).hexdigest()
if cur not in (m['before'],m['after']):
    raise SystemExit('STOP: production changed since review')
print('PASS reviewed source and production baseline')
PY

"$PYTHON" -m py_compile "$SOURCE/token_launch.py"

BACKUP="$(mktemp -d /opt/orcagent-claim-fix-backup.XXXXXX)"
chmod 700 "$BACKUP"
cp -a "$TARGET/token_launch.py" "$BACKUP/token_launch.py"
[ ! -f "$TARGET/VERSION" ] || cp -a "$TARGET/VERSION" "$BACKUP/VERSION"

rollback(){
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "Deploy failed; restoring previous claim route." >&2
    cp -a "$BACKUP/token_launch.py" "$TARGET/token_launch.py"
    [ ! -f "$BACKUP/VERSION" ] || cp -a "$BACKUP/VERSION" "$TARGET/VERSION"
    systemctl restart orcagent || true
  fi
  exit "$rc"
}
trap rollback EXIT

install -o orcagent -g orcagent -m 0644 "$SOURCE/token_launch.py" "$TARGET/token_launch.py"
git -c safe.directory="$SOURCE" -C "$SOURCE" rev-parse --short HEAD > "$TARGET/VERSION"
chown orcagent:orcagent "$TARGET/VERSION"
systemctl restart orcagent

healthy=0
for _ in {1..20}; do
  if systemctl is-active --quiet orcagent &&
     curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null; then
    healthy=1; break
  fi
  sleep 2
done
[ "$healthy" = 1 ] || { echo "Health check failed" >&2; exit 1; }

"$PYTHON" - "$TARGET/token_launch.py" "$MANIFEST" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1]);m=json.load(open(sys.argv[2]))['token_launch.py']
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['after']
print('PASS deployed claim route hash')
PY

echo "Deployment complete. Version: $(cat "$TARGET/VERSION")"
echo "Rollback backup: $BACKUP"
