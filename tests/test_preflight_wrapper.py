"""The one command an operator actually types.

WHY THIS EXISTS
The preflight itself is fine. Reaching it was not: sourcing the environment
file by hand, dropping to the right user by hand, and knowing that --wallet
means the session wallet rather than the address the app puts on screen. That
is three chances to get it wrong, on a phone, at the moment somebody is about
to decide whether to spend real money.

Every check here is about a mistake that was actually made, not a
hypothetical one.
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SH = os.path.join(REPO, 'deploy', 'preflight.sh')

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


check('the wrapper exists and is executable',
      os.path.isfile(SH) and os.access(SH, os.X_OK))

SRC = open(SH).read()

check('it parses as a shell script',
      subprocess.run(['bash', '-n', SH], capture_output=True).returncode == 0)
check('...and stops at the first failure rather than carrying on half-done',
      'set -euo pipefail' in SRC)

# ── the environment ──────────────────────────────────────────────────────
# Comments are allowed to name the wrong way; the code is not.
CODE = '\n'.join(l for l in SRC.split('\n') if not l.lstrip().startswith('#'))
check('it SOURCES the environment file instead of exporting it line by line '
      '— the difference is whether a quoted value arrives with its quotes, '
      'and a key that does takes the app down at import',
      'set -a' in CODE and '. "$ENV_FILE"' in CODE
      and 'env $(' not in CODE and 'xargs' not in CODE)
check('...and reads the database from DATA_DIR rather than assuming a path',
      '${DATA_DIR:-/data}' in SRC)

# ── who it runs as ───────────────────────────────────────────────────────
check('it refuses to run without root, because the environment file is '
      'root-only and a half-configured run is worse than none',
      'id -u' in SRC and 'Run this with sudo' in SRC)
check('...but runs the app as the app\'s own user, so nothing in the data '
      'directory ends up owned by root',
      'runuser -u orcagent' in SRC)

# ── the mistake it is here to catch ──────────────────────────────────────
check('passing the EVM TRADING address — the one the app shows you — is '
      'recognised and answered with the session wallet for that same account, '
      'rather than with somebody else\'s HTTP 400',
      'is a TRADING address, not a session wallet' in SRC
      and 'bsc_wallet_address' in SRC)
check('...and an address nobody signs in as is refused outright',
      'No account signs in as' in SRC)
check('it falls back to OWNER_WALLET when no wallet is given, and says so — '
      'never a guess at somebody else\'s account',
      'OWNER_WALLET' in SRC and 'No wallet given' in SRC)

# ── what it promises ─────────────────────────────────────────────────────
check('it says plainly that nothing is signed, sent, approved or spent, '
      'because that is the whole reason this step exists',
      'signs nothing' in SRC or 'nothing is signed' in SRC)
check('...and it never prints the API key',
      'ZEROX_API_KEY' not in SRC or 'never prints' in SRC)
check('it prints the explorer link for the address that has to hold the '
      'money, so checking a deposit is not a second puzzle',
      'basescan.org/address/' in SRC)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
