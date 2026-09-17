#!/usr/bin/env bash
# ── OrcAgent — is the cross-chain route ready for a real trade? ──
#
#     sudo bash /opt/orcagent/deploy/preflight.sh
#     sudo bash /opt/orcagent/deploy/preflight.sh <session wallet>
#     sudo bash /opt/orcagent/deploy/preflight.sh <session wallet> 30
#
# One command instead of a line nobody can type on a phone. It reads
# /etc/orcagent.env the way systemd does (quotes and all), works out which
# account to check, drops to the user the app runs as, and runs the read-only
# preflight.
#
# It signs nothing, sends nothing, approves nothing and spends nothing. The
# only credential it touches is the one already in the environment file, and
# it never prints it.
set -euo pipefail

APP_DIR=/opt/orcagent
ENV_FILE=/etc/orcagent.env

say(){ printf '\n\033[1;33m▸ %s\033[0m\n' "$*"; }
die(){ printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this with sudo — the environment file is root-only."
[ -r "$ENV_FILE" ]   || die "$ENV_FILE is missing or unreadable."
[ -d "$APP_DIR" ]    || die "$APP_DIR is not there. Is the app deployed?"

# Sourced, not exported line by line. systemd strips the quotes around a
# value; `env $(grep ...)` does not, and a key that arrives with a literal
# quote at index 0 takes the app down at import with a Rust panic. Ask how
# that was found.
set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

DB="${DATA_DIR:-/data}/orcagent.db"
[ -f "$DB" ] || die "No database at $DB."

WALLET="${1:-}"
AMOUNT="${2:-30}"

# ── which account? ──
# Given one, use it. Otherwise the owner's, because that is whose money a
# first live test is supposed to be. Never a guess at somebody else's.
if [ -z "$WALLET" ]; then
  WALLET="${OWNER_WALLET:-}"
  [ -n "$WALLET" ] || die "No wallet given and OWNER_WALLET is not set.

    Pass the SESSION wallet — the address you sign in with, not the trading
    address the app shows you:

        sudo bash $0 <session wallet>

    To find it from the 0x... address on your Portfolio page:

        sudo -u orcagent sqlite3 $DB \\
          \"SELECT wallet_address FROM users WHERE lower(bsc_wallet_address)=lower('<0x...>');\""
  say "No wallet given — using OWNER_WALLET"
fi

# ── does this account exist, and does it have the wallets the route needs? ──
ROW="$(sudo -u orcagent sqlite3 "$DB" \
  "SELECT id || '|' || COALESCE(bsc_wallet_address,'') FROM users WHERE wallet_address='$WALLET';" \
  2>/dev/null || true)"
if [ -z "$ROW" ]; then
  # The mistake this catches is passing the EVM trading address instead.
  OWNER_OF="$(sudo -u orcagent sqlite3 "$DB" \
    "SELECT wallet_address FROM users WHERE lower(bsc_wallet_address)=lower('$WALLET');" \
    2>/dev/null || true)"
  if [ -n "$OWNER_OF" ]; then
    die "$WALLET is a TRADING address, not a session wallet.

    That account signs in as:

        $OWNER_OF

    Run it again with that one."
  fi
  die "No account signs in as $WALLET."
fi

UID_="${ROW%%|*}"
EVM="${ROW#*|}"
say "Account $UID_"
echo "  session wallet  $WALLET"
echo "  EVM trading     ${EVM:-(none yet — the preflight will create one)}"
[ -n "$EVM" ] && echo "  balances        https://basescan.org/address/$EVM"

say "Preflight (read only — nothing is signed, sent or spent)"
cd "$APP_DIR"
exec runuser -u orcagent -- venv/bin/python scripts/crosschain_preflight.py \
     --amount "$AMOUNT" --wallet "$WALLET"
