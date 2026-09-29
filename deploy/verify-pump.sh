#!/usr/bin/env bash
# Dependency installation and read-only checks only. No wallet signing or send.
set -euo pipefail
ADAPTER="${1:?adapter directory required}"
ENV_FILE="${2:-/etc/orcagent.env}"
RUN="$ADAPTER/run-node.sh"
cd "$ADAPTER"
bash "$RUN" npm ci --omit=dev --ignore-scripts --no-audit --no-fund --quiet
bash "$RUN" test-security.cjs
bash "$RUN" npm audit --omit=dev --audit-level=high
bash "$RUN" -e "const s=require('@pump-fun/pump-sdk'); if(!s.PUMP_SDK || !s.OnlinePumpSdk) process.exit(1); console.log('PASS Pump SDK CommonJS import')"
# Read only the trusted RPC setting; never echo credentials or source env code.
TRUSTED_RPC="$(python3 - "$ENV_FILE" <<'PY'
import os,sys
if os.path.isfile(sys.argv[1]):
    for line in open(sys.argv[1],encoding='utf-8'):
        if line.lstrip().startswith('SOLANA_RPC_URL='):
            print(line.split('=',1)[1].strip().strip('"').strip("'"))
            break
PY
)"
if [ -n "$TRUSTED_RPC" ]; then
  ORCA_LAUNCH_RPC="$TRUSTED_RPC" bash "$RUN" read-only-preflight.cjs
else
  bash "$RUN" read-only-preflight.cjs
fi
