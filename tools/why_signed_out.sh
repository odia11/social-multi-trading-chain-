#!/usr/bin/env bash
# ── Why was somebody signed out? ──
#
#     sudo bash /opt/orcagent/tools/why_signed_out.sh [minutes]
#
# One command instead of three, because the person running it is on a phone
# and is already annoyed. It answers, in order:
#
#   1. Is the code that records any of this even deployed? An empty log means
#      nothing when the logging is not live, and that has already cost a
#      round trip.
#   2. What did the remembered-login path actually do?
#   3. Did anything revoke logins -- the only thing that signs a wallet out on
#      devices other than the one asking.
#
# Read-only. Prints no wallet in full and no token.
set -uo pipefail

MINS="${1:-60}"
APP_DIR=/opt/orcagent

say(){ printf '\n\033[1;33m▸ %s\033[0m\n' "$*"; }

say "Which code is running"
DEPLOYED=""
[ -f "$APP_DIR/VERSION" ] && DEPLOYED="$(cat "$APP_DIR/VERSION" 2>/dev/null)"
if [ -z "$DEPLOYED" ]; then
  echo "  No VERSION file at $APP_DIR."
  echo "  That means the deploy that added this script has NOT been run yet,"
  echo "  so the sign-out logging below does not exist and an empty result"
  echo "  proves nothing. Run:  sudo bash ~/orcagent/deploy/update.sh"
else
  echo "  deployed commit: $DEPLOYED"
  CLONE=""
  for c in /home/*/orcagent /root/orcagent; do [ -e "$c/.git" ] && { CLONE="$c"; break; }; done
  if [ -n "$CLONE" ]; then
    LATEST="$(git -C "$CLONE" rev-parse --short HEAD 2>/dev/null || echo '?')"
    echo "  latest in the clone: $LATEST"
    [ "$LATEST" != "$DEPLOYED" ] && \
      echo "  ⚠ these differ — the server is NOT running the newest code"
  fi
fi

say "What the remembered-login path did (last ${MINS} min)"
LINES="$(journalctl -u orcagent --since "${MINS} min ago" --no-pager 2>/dev/null \
         | grep -F '[device-session]' || true)"
if [ -z "$LINES" ]; then
  echo "  nothing at all."
  if [ -n "$DEPLOYED" ]; then
    cat <<'NOTE'
  With the logging deployed, that is itself the finding: no browser asked to
  resume in this window. So the page never got as far as trying -- it either
  believed it was signed in, or it never reached the code that asks. It is
  NOT the case that a remembered login was refused.
NOTE
  fi
else
  printf '%s\n' "$LINES" | sed 's/^/  /'
fi

say "Did anything sign a wallet out everywhere?"
REV="$(printf '%s\n' "$LINES" | grep -F 'REVOKED' || true)"
if [ -z "$DEPLOYED" ]; then
  # "No revocations found" and "nothing is recording revocations" look
  # identical from here, and reporting the first when it is the second is
  # exactly the false confidence this script exists to stop.
  echo "  cannot tell — the logging is not deployed yet. Not the same as \"no\"."
elif [ -z "$REV" ]; then
  echo "  no. Nothing revoked a remembered login, so whatever happened was"
  echo "  local to one browser rather than an account-wide sign-out."
else
  printf '%s\n' "$REV" | sed 's/^/  /'
  echo
  echo "  Something called Disconnect. That is the only path that does this."
fi

say "Also worth having"
echo "  Where did it happen — Safari, the app on the home screen, or Phantom's"
echo "  own browser? Those are three separate storage areas and the answer"
echo "  decides which one to look at."
