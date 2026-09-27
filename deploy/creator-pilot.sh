#!/usr/bin/env bash
# OrcAgent limited funded mainnet pilot; only the named public Phantom wallet.
# Usage: sudo bash ~/orcagent/deploy/creator-pilot.sh <PUBLIC_SOLANA_WALLET>
# Stop:  sudo bash ~/orcagent/deploy/creator-pilot.sh --disable
# Does not sign, send, buy, sell, swap, create or claim anything on-chain.
set -euo pipefail
APP_DIR=/opt/orcagent
ENV_FILE=/etc/orcagent.env
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ "$(id -u)" -eq 0 ] || { echo 'Run with sudo.' >&2; exit 1; }
[ "$#" -eq 1 ] || { echo 'Give one public Solana wallet address or --disable.' >&2; exit 1; }
[ -f "$ENV_FILE" ] && [ -f "$APP_DIR/token_launch.py" ] || { echo 'Missing OrcAgent production environment or app.' >&2; exit 1; }
if grep -Eq '^[[:space:]]*ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED=1[[:space:]]*$' "$ENV_FILE"; then
  echo 'Refusing to modify a currently public Token Launch configuration.' >&2
  exit 1
fi
if [ "$1" != '--disable' ]; then
  WALLET="$1"
  "$APP_DIR/venv/bin/python" - "$WALLET" <<'PY'
import sys
from solders.pubkey import Pubkey
try:
    value=sys.argv[1]
    if str(Pubkey.from_string(value))!=value or value=='11111111111111111111111111111111':
        raise ValueError
except ValueError:
    sys.exit('Invalid public Solana wallet address. No settings changed.')
print('Creator pilot public wallet format confirmed.')
PY
  DEPLOYED="$(cat "$APP_DIR/VERSION" 2>/dev/null || true)"
  SOURCE="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
  [ "$DEPLOYED" = "$SOURCE" ] || { echo 'Deploy the latest repository code before configuring the pilot. No settings changed.' >&2; exit 1; }
  grep -q 'PILOT_MAX_LAUNCH_SOL_LAMPORTS' "$APP_DIR/token_launch.py" || { echo 'Budget-guarded pilot not deployed. No settings changed.' >&2; exit 1; }
  grep -q 'pilot_creator_only' "$APP_DIR/templates/token_launch.html" || { echo 'Creator pilot page not deployed. No settings changed.' >&2; exit 1; }
  echo 'Installing and validating pinned Pump runtime and adapter (no transactions sent)...'
  bash "$REPO_DIR/deploy/install-pump-runtime.sh"
  bash "$REPO_DIR/deploy/verify-pump.sh" "$APP_DIR/pump_adapter" "$ENV_FILE"
  chown -R orcagent:orcagent "$APP_DIR/pump_adapter/node_modules"
fi
BACKUP="$(mktemp /etc/orcagent.env.pilot-backup.XXXXXX)"
chmod 600 "$BACKUP"
cp -p "$ENV_FILE" "$BACKUP"
restore(){
  rc=$?
  if [ "$rc" -ne 0 ]; then
    cp -p "$BACKUP" "$ENV_FILE"
    systemctl restart orcagent || true
    echo 'Pilot setup failed; original environment restored.' >&2
  fi
  rm -f "$BACKUP"
}
trap restore EXIT
if [ "$1" = '--disable' ]; then
  TEST_FLAG=0
  WALLET=''
else
  TEST_FLAG=1
fi
"$APP_DIR/venv/bin/python" - "$ENV_FILE" "$TEST_FLAG" "$WALLET" <<'PY'
import os,sys,tempfile
from pathlib import Path
p=Path(sys.argv[1]);enabled=sys.argv[2];wallet=sys.argv[3]
keys={'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED',
      'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED',
      'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS'}
lines=[line for line in p.read_text().splitlines(keepends=True)
       if line.split('=',1)[0].strip() not in keys]
lines += ['\nORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED=0\n',
          'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED='+enabled+'\n',
          'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS='+wallet+'\n']
st=p.stat()
fd,name=tempfile.mkstemp(dir=str(p.parent),prefix='.orca-pilot-',text=True)
try:
    os.fchmod(fd,st.st_mode&0o777)
    os.fchown(fd,st.st_uid,st.st_gid)
    with os.fdopen(fd,'w',encoding='utf-8') as f:f.writelines(lines)
    os.replace(name,p)
except BaseException:
    try:os.unlink(name)
    except FileNotFoundError:pass
    raise
PY
systemctl restart orcagent
sleep 3
curl -fsS --max-time 9 http://127.0.0.1:8080/health >/dev/null
systemctl is-active --quiet orcagent
# Verify what the running service actually inherited, not just the file written.
SERVICE_PID="$(systemctl show orcagent --property=MainPID --value)"
"$APP_DIR/venv/bin/python" - "$SERVICE_PID" "$TEST_FLAG" "$WALLET" <<'VERIFY'
import sys
from pathlib import Path
pid,enabled,wallet=sys.argv[1:]
if not pid.isdigit() or int(pid)<=0:
    sys.exit('Pilot verification failed: service PID unavailable')
items=Path('/proc/'+pid+'/environ').read_bytes().split(b'\0')
env=dict(item.decode().split('=',1) for item in items if b'=' in item)
expected={'ORCAGENT_PUMP_TOKEN_LAUNCH_ENABLED':'0',
          'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_ENABLED':enabled,
          'ORCAGENT_PUMP_TOKEN_LAUNCH_TEST_WALLETS':wallet}
if any(env.get(key)!=value for key,value in expected.items()):
    sys.exit('Pilot verification failed: running service settings differ')
print('PASS running service: public launches OFF; exact private pilot settings verified')
VERIFY
if [ "$1" = '--disable' ]; then
  echo 'Pilot disabled; app healthy. No on-chain action was taken.'
else
  echo 'Private USDC/100% creator pilot enabled ONLY for the named public wallet.'
  echo 'Budget plan: 0.03 SOL total. Launch simulation is capped at 0.025 SOL; reserve 0.005 SOL for follow-up.'
  echo 'The external manual test trade is NOT budget-enforced by Token Launch; check cumulative costs in Phantom.'
  echo '2 USDC manual trade only; inspect Phantom before approving each action.'
  echo 'The public token-launch switch remains OFF. No on-chain action was taken.'
fi
