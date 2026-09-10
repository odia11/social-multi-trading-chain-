"""Logging in must work in a browser that already has a session.

WHAT HAPPENED
    Could not prepare signature request: CSRF validation failed

Connecting with Phantom is a four-step round trip through the deeplink:
init, decrypt, sign-init, decrypt-signature -- and then /api/wallet/set,
which verifies the signature and is what actually logs you in.

Steps 1 and 3 were exempt from the CSRF token check. Steps 2 and 4 were not.

That went unnoticed because the check only bites when the session ALREADY has
a wallet. A first login has no session, sends no token, and is never asked for
one. But reconnecting from a browser that still holds a session -- exactly
what someone does when the app has stopped showing them as signed in while
the cookie is still there -- hit a 403 on step 2 and could never finish.

WHY EXEMPTION IS THE RIGHT ANSWER
A page whose entire purpose is to establish a session cannot be required to
present a token that only exists once there is one. That is the same reason
/api/wallet/set and /api/phantom/init were already exempt; these two were
simply missed.

Nothing in the chain acts on who the session says you are. Each step works
from a server-generated token held for ten minutes, and the Origin check
applies to all of them, exempt or not.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
CB = open(REPO + '/templates/phantom_callback.html', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def _decorators(func_name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == func_name)
    out = []
    for d in f.decorator_list:
        out.append(ast.unparse(d))
    return out


# Every step of the login round trip, in order.
CHAIN = {
    '/api/phantom/init':              'api_phantom_init',
    '/api/phantom/decrypt':           'api_phantom_decrypt',
    '/api/phantom/sign-init':         'api_phantom_sign_init',
    '/api/phantom/decrypt-signature': 'api_phantom_decrypt_signature',
    '/api/wallet/set':                'set_wallet',
}

exempt_paths = re.search(r'_CSRF_EXEMPT_PATHS = frozenset\(\{(.*?)\}\)', SRC, re.S).group(1)

blocked = []
for path, func in CHAIN.items():
    by_decorator = '@csrf_exempt' in _decorators(func) or 'csrf_exempt' in _decorators(func)
    by_path = f"'{path}'" in exempt_paths
    if not (by_decorator or by_path):
        blocked.append(path)
for b in blocked:
    print('   still requires a CSRF token: ' + b)

check('EVERY step of the wallet login is exempt from the CSRF token check. '
      'Not most of them: the chain runs in a browser that has no session, so '
      'a single step demanding a token breaks the whole login',
      not blocked)

# The specific pair that was missed, named so a regression says which.
check('...including sign-init, the step that failed with "Could not prepare '
      'signature request"',
      'csrf_exempt' in ' '.join(_decorators('api_phantom_sign_init')))
check('...and decrypt-signature, the step immediately after it',
      'csrf_exempt' in ' '.join(_decorators('api_phantom_decrypt_signature')))

# ── it is exemption from the TOKEN only ──────────────────────────────────
check('exemption skips the token and nothing else — the Origin check runs '
      'first and applies to exempt paths too',
      SRC.index('origin = request.headers.get') < SRC.index('_csrf_exempt', SRC.index('def _csrf_check')))
check('...and every step is still rate limited, being unauthenticated',
      all('rate_limit' in ' '.join(_decorators(f))
          for f in ('api_phantom_init', 'api_phantom_sign_init',
                    'api_phantom_decrypt_signature')))

# ── why the callback page cannot simply send one ─────────────────────────
check('the callback page sends no CSRF token, because in the browser Phantom '
      'hands back to there is no session to have issued one',
      'X-CSRF' not in CB)

# ── the check only bites for a session that has a wallet ─────────────────
guard = SRC[SRC.index('def _csrf_check'):]
guard = guard[:guard.index('CSRF validation failed')]
check('the token check applies only once a session HAS a wallet, which is why '
      'this survived so long: a first login never triggers it, and only '
      'reconnecting does', "if session.get('wallet'):" in guard)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
