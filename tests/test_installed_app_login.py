"""Connect in the browser, add to the home screen, still connected.

THE BOUNDARY
On iOS an app added to the home screen gets its OWN storage container:
separate cookies AND separate localStorage. So neither the session made in
Safari nor the remembered login stored beside it is visible from inside the
installed app. And the app cannot make its own -- tapping Connect there hands
off to Phantom's deeplink, which opens Safari, and the new session lands over
there instead. Connect in the browser, add to the home screen, get asked to
connect again. Forever.

Remembered logins did not fix this, because they live in localStorage, which
does not cross that boundary either.

WHAT DOES CROSS IT
Exactly one thing: the start_url baked into the manifest at the moment the
app is installed. So the manifest is served per session, with a one-time
token in that URL, and the installed app's first launch spends it for a
session of its own -- and then asks for a remembered login, so it never has
to do this again.
"""
import ast
import hashlib
import os
import re
import secrets
import sqlite3
import sys
import tempfile
import time

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

# ── 1. the manifest carries the login ─────────────────────────────────────
mf = fn('app_webmanifest')
check('the manifest is generated per session rather than served as a static '
      'file — a fixed start_url can carry nothing',
      "session.get('wallet'" in mf and 'start_url' in mf)
check('...with a one-time token in start_url when the person adding it to '
      'their home screen is signed in', "'/?hs=' + tok" in mf)
check('...and the plain start_url when they are not, so a signed-out install '
      'is an ordinary manifest', "start = '/'" in mf)
check('...never cached: the response is specific to one person and contains a '
      "credential", "'no-store" in mf and 'private' in mf)

pages = [p for p in os.listdir(REPO + '/templates') if p.endswith('.html')]
linked = [p for p in pages
          if 'rel="manifest"' in open(REPO + '/templates/' + p).read()]
bad = [p for p in linked
       if 'crossorigin="use-credentials"' not in open(REPO + '/templates/' + p).read()]
check('every page linking the manifest asks for it WITH credentials — without '
      'that attribute the browser fetches it anonymously and the token is '
      'never minted', linked and not bad)
check('...including the dashboard itself',
      'crossorigin="use-credentials"' in open(REPO + '/dashboard.html').read())
check('nothing still points at the old static manifest',
      not any('static/manifest.json' in open(REPO + '/templates/' + p).read()
              for p in pages)
      and 'static/manifest.json' not in open(REPO + '/dashboard.html').read())

# ── 2. spending it on first launch ────────────────────────────────────────
idx = fn('index')
check('the first launch of the installed app spends the token from its '
      'start_url', "request.args.get('hs'" in idx and '_redeem_handoff_token' in idx)
check('...and gets a real session out of it, permanent like any other login',
      'session.permanent = True' in idx and "session['wallet']" in idx)
check('...with any read-only flag cleared, so a launched app is never signed '
      'in but treated as nobody', "session.pop('readonly'" in idx)
check('...then redirects, taking the token out of the address bar and out of '
      'history — and so a reload does not present a spent one',
      "return redirect('/')" in idx)
check('a token that is spent, expired or unknown falls through silently to '
      'the normal page. The start_url is permanent, so EVERY later launch '
      'presents the same one and none of them is an error',
      idx.count('redirect') == 1 and 'abort' not in idx)

# ── 3. run the real thing ─────────────────────────────────────────────────
with tempfile.TemporaryDirectory() as tmp:
    db = os.path.join(tmp, 't.db')
    conn = sqlite3.connect(db)
    conn.execute('''CREATE TABLE app_handoffs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, wallet TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
        expires_at REAL NOT NULL, used_at REAL)''')
    conn.commit(); conn.close()

    complaints = []
    days = next(int(ast.literal_eval(n.value)) for n in ast.walk(TREE)
                if isinstance(n, ast.Assign)
                and any(getattr(t, 'id', '') == 'HANDOFF_TOKEN_DAYS' for t in n.targets))
    ns = {'sqlite3': sqlite3, 'hashlib': hashlib, 'secrets': secrets, 'time': time,
          'DB_FILE': db, 'HANDOFF_TOKEN_DAYS': days,
          'print': lambda *a, **k: complaints.append(' '.join(str(x) for x in a))}
    for name in ('_hash_device_token', '_issue_handoff_token', '_redeem_handoff_token'):
        exec(fn(name), ns)

    tok = ns['_issue_handoff_token']('WALLET_A')
    check('issuing a handoff returns a token', bool(tok) and len(tok) > 20)
    if complaints:
        print('   the code complained: ' + ' | '.join(complaints))
    check('...with no complaint from the storage layer', not complaints)

    stored = sqlite3.connect(db).execute('SELECT token_hash FROM app_handoffs').fetchall()
    check('...and only its hash is stored, so a copy of the table is not a set '
          'of usable logins',
          all(tok not in r[0] for r in stored)
          and stored[0][0] == hashlib.sha256(tok.encode()).hexdigest())

    check('redeeming it returns the wallet it was minted for',
          ns['_redeem_handoff_token'](tok) == 'WALLET_A')
    check('...and it is SINGLE USE. The start_url is baked into the installed '
          'app permanently, so this token is presented on every launch — it '
          'must open exactly one session, not one per launch, forever',
          ns['_redeem_handoff_token'](tok) == '')

    t2 = ns['_issue_handoff_token']('WALLET_B')
    c = sqlite3.connect(db)
    c.execute('UPDATE app_handoffs SET expires_at=? WHERE token_hash=?',
              (time.time() - 1, hashlib.sha256(t2.encode()).hexdigest()))
    c.commit(); c.close()
    check('an expired handoff is refused', ns['_redeem_handoff_token'](t2) == '')
    check('an unknown one is refused', ns['_redeem_handoff_token']('nonsense') == '')
    check('an empty one is refused without touching the database',
          ns['_redeem_handoff_token']('') == '')
    check('a handoff is short-lived next to a remembered login — it exists to '
          'open one app once, not to be a login of its own', days <= 30)

# ── 4. the launched app gets remembered, or it is back here next week ─────
rem = fn('api_session_remember')
check('a session that nothing remembers can ask to be remembered — the '
      'installed app arrives with exactly that, and so does anyone signed in '
      'from before remembered logins existed',
      '_issue_device_token(' in rem)
check('...but it mints nothing without an authenticated session, so it is not '
      'a way in', '_authenticated_wallet()' in rem and '401' in rem)
check('...and a read-only session gets nothing, since that would make '
      'persistent a claim that was never proved',
      '_authenticated_wallet()' in rem)
check('...and it is rate limited', '@rate_limit' in SRC[SRC.index('def api_session_remember') - 200:
                                                       SRC.index('def api_session_remember')])
check('the page asks for one exactly when it has a session but nothing '
      'remembering it', 'api/session/remember' in JS and 'if(!_deviceToken())' in JS)
check('...and stores what comes back, or the round trip achieved nothing',
      '_storeDeviceToken(_rm.token)' in JS)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
