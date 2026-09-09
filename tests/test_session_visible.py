"""A page must never infer "logged out" from its own HTML being quiet.

THE BUG
Who is signed in reached the frontend exactly one way: __SESSION_WALLET,
string-replaced into the HTML. That substitution happens in two routes — /
and /dashboard. Six pages load dashboard.js.

On the other four the variable was undefined, so `phantomKey` stayed null,
initApp ran as though nobody were signed in, and it went off to ask the
wallet for a fresh signature. A user with a perfectly valid server session
was told to connect again — every time they opened Live Market. The session
was never lost; the page simply never asked whether there was one.

Worse, the manual-disconnect flag is only cleared when phantomKey is set, so
on those pages it never cleared: once a user had disconnected by hand, those
pages stayed logged out for good.

THE RULE
The server is the authority on who is signed in. When the HTML has not
already answered it, the page asks — one GET, and only then.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
JS = open(REPO + '/static/dashboard.js').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


# ── there has to be something to ask ──────────────────────────────────────
check('the server can be asked who is signed in', "@app.route('/api/session'" in SRC)
sess = fn('api_session')
check('...over GET, so it is not caught by the CSRF check and needs no token '
      'to answer the question of whether you have one',
      "methods=['GET']" in SRC[SRC.index("@app.route('/api/session'"):
                                SRC.index("@app.route('/api/session'") + 120])
check('...returning the wallet the session holds', "session.get('wallet', '')" in sess)
check('...and separating a READ-ONLY session, which has an address but has '
      'proved nothing — the same distinction _authenticated_wallet() makes',
      "'readonly': readonly" in sess and "'authenticated': bool(wallet) and not readonly" in sess)
check('...issuing a CSRF token only when a session already exists, rather '
      'than minting one for an anonymous caller',
      "_get_csrf_token() if wallet else ''" in sess)
check('...and nothing secret: no key, no encrypted blob',
      'PRIVATE_KEY' not in sess and 'encrypted' not in sess)

auth = fn('_authenticated_wallet')
check('the endpoint agrees with the function that guards everything else — '
      'both treat a read-only session as nobody',
      "session.get('readonly')" in auth and "session.get('readonly')" in sess)

# ── the page has to actually ask ──────────────────────────────────────────
check('the frontend asks the server when the HTML did not tell it',
      "fetch('/api/session'" in JS)
check('...only when the injection did not already answer, so the common page '
      'pays nothing', 'if(!phantomKey){' in JS
      and JS.index('if(!phantomKey){') < JS.index("fetch('/api/session'"))
check('...and applies it through the same path the injected value uses, so '
      'the navbar fills in either way',
      '_applySessionWallet(_me.wallet)' in JS
      and '_applySessionWallet(window.__SESSION_WALLET' in JS)
check('...taking the CSRF token with it, or the first write from that page '
      'would be rejected', '_csrfToken = _me.csrf_token' in JS)
check('...and only when the server says AUTHENTICATED, not merely that an '
      'address is present', '_me.authenticated' in JS)

# ── the disconnect flag must not outrank the server ───────────────────────
check('the manual-disconnect check runs AFTER the server has been asked, so a '
      'flag left behind on a page that never cleared it cannot keep a signed-in '
      'user logged out',
      JS.index("fetch('/api/session'")
      < JS.index("localStorage.getItem('orca_manual_disconnect') && !phantomKey"))

# ── the pages that were broken ────────────────────────────────────────────
import os
loaders = [f for f in os.listdir(REPO + '/templates')
           if f.endswith('.html')
           and 'dashboard.js' in open(REPO + '/templates/' + f).read()]
check(f'the pages that load dashboard.js are still the ones this is about '
      f'({len(loaders)} of them), and none of them injects the wallet — which '
      f'is exactly why asking is the fix rather than adding a sixth copy of a '
      f'string replacement',
      len(loaders) >= 4
      and not any('__SESSION_WALLET' in open(REPO + '/templates/' + f).read()
                  for f in loaders))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
