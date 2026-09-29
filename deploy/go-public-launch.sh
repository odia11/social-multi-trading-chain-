#!/usr/bin/env bash
# Owner-approved rollout: deploy tested code, THEN enable authenticated public launches.
# No wallet signing, transaction broadcast, mint creation or on-chain spending.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP=/opt/orcagent
ENV_FILE=/etc/orcagent.env
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo from Termius.' >&2; exit 1; }
[ -d "$ROOT/.git" ] || { echo 'Run the script in the source repository, not /opt.' >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo 'Missing production environment; no changes made.' >&2; exit 1; }

# Deploy first: before this succeeds the existing private pilot remains intact.
if [ "$(cat "$APP/VERSION" 2>/dev/null || true)" != "$(git -C "$ROOT" rev-parse --short HEAD)" ]; then
  bash "$ROOT/deploy/update.sh"
fi
[ "$(cat "$APP/VERSION")" = "$(git -C "$ROOT" rev-parse --short HEAD)" ] \
  || { echo 'Production code is not current; public launch unchanged.' >&2; exit 1; }
for marker in PUBLIC_MAX_LAUNCH_SOL_LAMPORTS enforce_public; do
  grep -q "$marker" "$APP/token_launch.py" \
    || { echo 'Public cost gate is missing; public launch unchanged.' >&2; exit 1; }
done
[ -f "$APP/pump_adapter/node_modules/@pump-fun/pump-sdk/package.json" ] \
  || { echo 'Pinned Pump SDK is missing; public launch unchanged.' >&2; exit 1; }
bash "$APP/pump_adapter/run-node.sh" "$APP/pump_adapter/test-security.cjs" \
  || { echo 'Pump SDK safety preflight failed; public launch unchanged.' >&2; exit 1; }
systemctl is-active --quiet orcagent
curl -fsS --max-time 9 http://127.0.0.1:8080/health >/dev/null

BACKUP="$(mktemp /etc/orcagent.env.public-backup.XXXXXX)"
chmod 600 "$BACKUP"
cp -p "$ENV_FILE" "$BACKUP"
ROLLED_OUT=0
restore(){
  local status=$?
  if [ "$ROLLED_OUT" != 1 ]; then
    cp -p "$BACKUP" "$ENV_FILE"
    systemctl restart orcagent || true
    echo 'Public launch activation failed. Prior pilot configuration restored.' >&2
  fi
  rm -f "$BACKUP"
  exit "$status"
}
trap restore EXIT
"$APP/venv/bin/python" - "$ENV_FILE" <<'PY'
import os,sys,tempfile
from pathlib import Path
path=Path(sys.argv[1]);old=path.read_text().splitlines(keepends=True)
keys={'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED','ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED'}
clean=[line for line in old if line.split('=',1)[0].strip() not in keys]
clean += ['\nORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED=1\n',
          'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED=0\n']
st=path.stat()
fd,tmp=tempfile.mkstemp(prefix='.orca-public-launch-',dir=path.parent,text=True)
try:
    os.fchmod(fd,st.st_mode&0o777)
    os.fchown(fd,st.st_uid,st.st_gid)
    with os.fdopen(fd,'w',encoding='utf-8') as f:f.writelines(clean)
    os.replace(tmp,path)
except BaseException:
    try:os.unlink(tmp)
    except FileNotFoundError:pass
    raise
PY
systemctl restart orcagent
sleep 3
systemctl is-active --quiet orcagent
curl -fsS --max-time 12 http://127.0.0.1:8080/health >/dev/null
PID="$(systemctl show orcagent -p MainPID --value)"
"$APP/venv/bin/python" - "$PID" <<'PY'
from pathlib import Path
import sys
pid=sys.argv[1]
if not pid.isdigit() or int(pid)<=0:sys.exit('No running service PID')
data=Path('/proc/'+pid+'/environ').read_bytes().split(b'\0')
env=dict(item.decode().split('=',1) for item in data if b'=' in item)
if env.get('ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED')!='1' or env.get('ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED')!='0':
    sys.exit('Running service does not have public Token Launch settings')
print('PASS running service: public token launches ENABLED, private-pilot-only mode OFF')
PY
ROLLED_OUT=1
printf 'OrcAgent public Solana Token Launch is live on version %s. No on-chain action performed by this script.\n' "$(cat "$APP/VERSION")"
