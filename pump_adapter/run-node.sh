#!/usr/bin/env bash
# Shared by installer, preflight and ALL Python transaction builders.
set -euo pipefail
ADAPTER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(cat "$ADAPTER/.node-version")"
NODE="${ORCAGENT_PUMP_NODE:-/opt/orcagent-runtime/node-v$VERSION/bin/node}"
[[ "$NODE" = /* && -x "$NODE" ]] || { echo 'Pinned Pump Node runtime missing.' >&2; exit 1; }
# Do not allow inherited NODE_OPTIONS/NODE_PATH to change SDK resolution.
unset NODE_OPTIONS NODE_PATH
"$NODE" "$ADAPTER/runtime-check.cjs"
export PATH="$(dirname "$NODE"):/usr/bin:/bin"
if [ "${1:-}" = npm ]; then
  shift
  exec "$NODE" "$(dirname "$NODE")/../lib/node_modules/npm/bin/npm-cli.js" "$@"
fi
exec "$NODE" "$@"
