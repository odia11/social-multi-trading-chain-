"""Connect a wallet once, stay connected.

WHY A COOKIE IS NOT ENOUGH
iOS clears storage for sites left unused for a week, and an app added to the
home screen keeps its own cookie jar — so a perfectly valid login made in
Safari is invisible from inside it. And an installed app cannot complete the
Phantom deeplink to make a new one: it opens the browser, and the session
lands there. Losing the cookie there means being locked out.

So a proven connection also mints a long-lived token the browser keeps, which
is exchanged for a fresh session when the cookie is gone.

WHAT THAT OBLIGES
Only the hash is stored, so a copy of the table is not a set of usable
logins. It rotates on every use: if a stolen token is redeemed, the real
owner's copy stops working, which turns silent sharing into a visible logout.
It is minted only where a signature was actually verified. And Disconnect
revokes every one of them — a session that clears and then quietly resumes
tomorrow is the opposite of what that button says.

The redeem path is exercised against a real database rather than read.
"""
import ast
import os
import re
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


# ── run the real issue/redeem/revoke cycle ────────────────────────────────
import hashlib, secrets                                        # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    db = os.path.join(tmp, 't.db')
    conn = sqlite3.connect(db)
    conn.execute('''CREATE TABLE device_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        wallet TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
        created_at REAL NOT NULL, last_used_at REAL NOT NULL,
        expires_at REAL NOT NULL, revoked INTEGER DEFAULT 0)''')
    conn.commit(); conn.close()

    # The real constant, not a guess: if it is renamed or removed, this test
    # says so instead of quietly exercising a different lifetime.
    days = next(int(ast.literal_eval(n.value))
                for n in ast.walk(TREE)
                if isinstance(n, ast.Assign)
                and any(getattr(t, 'id', '') == 'DEVICE_TOKEN_DAYS'
                        for t in n.targets))

    # These functions swallow their exceptions and print. Keep the messages
    # instead of discarding them -- a no-op print here once hid a NameError
    # for the whole run and left the failure looking like a logic bug.
    complaints = []
    ns = {'sqlite3': sqlite3, 'hashlib': hashlib, 'secrets': secrets,
          'time': time, 'DB_FILE': db, 'DEVICE_TOKEN_DAYS': days,
          'print': lambda *a, **k: complaints.append(' '.join(str(x) for x in a))}
    for name in ('_hash_device_token', '_issue_device_token',
                 '_redeem_device_token', '_revoke_device_tokens'):
        exec(fn(name), ns)

    tok = ns['_issue_device_token'](7, 'WALLET_A')
    check('issuing returns a token', bool(tok) and len(tok) > 20)
    if complaints:
        print('   the code complained: ' + ' | '.join(complaints))
    check('...without the storage layer complaining about anything',
          not complaints)

    check('the remembered login lasts months, not a browser session -- the '
          'whole point is surviving a week of not opening the app',
          days >= 30)

    stored = sqlite3.connect(db).execute(
        'SELECT token_hash FROM device_sessions').fetchall()
    check('...and the token itself is NOT stored — only its hash, so a copy of '
          'this table is not a set of usable logins',
          all(tok not in r[0] for r in stored)
          and stored[0][0] == hashlib.sha256(tok.encode()).hexdigest())

    wallet, tok2 = ns['_redeem_device_token'](tok)
    check('redeeming returns the wallet it was issued for', wallet == 'WALLET_A')
    check('...and a DIFFERENT token, because it rotates on use',
          bool(tok2) and tok2 != tok)

    again, _ = ns['_redeem_device_token'](tok)
    check('...leaving the presented one dead. A stolen copy redeemed once '
          'signs the other side out, so theft is visible rather than silent',
          again == '')
    check('...while the replacement works', ns['_redeem_device_token'](tok2)[0] == 'WALLET_A')

    check('an unknown token is refused', ns['_redeem_device_token']('nonsense')[0] == '')
    check('an empty token is refused without touching the database',
          ns['_redeem_device_token']('')[0] == '')

    t3 = ns['_issue_device_token'](7, 'WALLET_A')
    c = sqlite3.connect(db)
    c.execute('UPDATE device_sessions SET expires_at=? WHERE token_hash=?',
              (time.time() - 1, hashlib.sha256(t3.encode()).hexdigest()))
    c.commit(); c.close()
    check('an expired token is refused', ns['_redeem_device_token'](t3)[0] == '')

    a = ns['_issue_device_token'](7, 'WALLET_A')
    b = ns['_issue_device_token'](7, 'WALLET_A')
    other = ns['_issue_device_token'](9, 'WALLET_B')
    ns['_revoke_device_tokens']('WALLET_A')
    check('disconnecting revokes EVERY remembered login for that wallet, not '
          'only the one in this browser — someone pressing it because they are '
          'worried means every device',
          ns['_redeem_device_token'](a)[0] == '' and ns['_redeem_device_token'](b)[0] == '')
    check('...and leaves other wallets alone',
          ns['_redeem_device_token'](other)[0] == 'WALLET_B')

# ── it must only be mintable off a real signature ─────────────────────────
setter = fn('wallet_set') if any(
    isinstance(n, ast.FunctionDef) and n.name == 'wallet_set' for n in ast.walk(TREE)) else SRC
# Counting callers was the old shape of this check, and it broke the moment a
# second legitimate caller appeared -- which taught nothing, because the rule
# was never "one caller". The rule is that EVERY caller stands behind proof of
# ownership. So they are enumerated and each one named.
_minters = sorted(
    n.name for n in ast.walk(TREE)
    if isinstance(n, ast.FunctionDef)
    and n.name != '_issue_device_token'          # its own definition, not a caller
    and '_issue_device_token(' in (ast.get_source_segment(SRC, n) or ''))
check('every place that mints a remembered login is one that has already '
      'established who this is: the wallet login, and the endpoint that '
      'remembers a session which is itself already authenticated. Nothing '
      'else may mint one — a remembered login outlives the browser, so an '
      'unproved claim would become a permanent one',
      _minters == ['api_session_remember', 'set_wallet'], )
check('...and the wallet login mints one only AFTER the signature has been '
      'checked, not beside it',
      'Signature verification failed' in SRC[:SRC.index('_device_token =')])
check('...while the remembering endpoint refuses a read-only session, which '
      'is an address someone typed and never proved',
      '_authenticated_wallet()' in fn('api_session_remember'))

resume = fn('api_session_resume')
check('the resume endpoint gives one answer for expired, revoked, unknown and '
      'malformed, rather than telling a guesser which it was',
      resume.count('401') == 1 and 'no longer remembered' in resume)
check('...and is CSRF-exempt for the same reason the connect endpoint is: it '
      'establishes the session, so it cannot require a token scoped to one',
      '@csrf_exempt' in SRC[SRC.index("@app.route('/api/session/resume'"):
                             SRC.index("@app.route('/api/session/resume'") + 200])
check('...rate limited, since it is an unauthenticated endpoint that hands out '
      'sessions', '@rate_limit(20, 300)' in SRC[
          SRC.index("@app.route('/api/session/resume'"):
          SRC.index("@app.route('/api/session/resume'") + 200])
check('...and clears any read-only flag, so resuming cannot leave a session '
      'that is signed in but treated as nobody', "session.pop('readonly', None)" in resume)

logout = fn('logout')
check('logging out revokes the remembered logins before clearing the session',
      '_revoke_device_tokens(' in logout
      and logout.index('_revoke_device_tokens') < logout.index('session.clear()'))

# ── the browser side ──────────────────────────────────────────────────────
check('the token is stored at the single point every wallet login passes '
      'through, not at each caller that reads the result',
      JS.count('r.device_token) _storeDeviceToken') == 1)
check('the session is resumed BEFORE anyone is sent back to their wallet app '
      'for a signature they already gave',
      '_resumeFromDeviceToken()' in JS
      and JS.index('await _resumeFromDeviceToken()') < JS.index("orca_manual_disconnect') && !phantomKey"))
# Measured from the session check forward, not from the top of the file: the
# helper is DEFINED hundreds of lines earlier, so searching for its name from
# index 0 lands on the definition and leaves nothing between the two points.
_branch = JS[JS.index('if(_me && _me.authenticated'):]
_branch = _branch[:_branch.index('_resumeFromDeviceToken()')]
check('...only when the server said there was no session, so a normal load '
      'costs nothing extra',
      # The resume must sit on the far side of the else. Checking that no
      # `await` appears before it was a proxy for that, and a wrong one: the
      # signed-in branch legitimately awaits now (it asks to be remembered).
      # What matters is which branch the resume is in, so that is what is
      # asked.
      '} else {' in _branch
      and '_resumeFromDeviceToken' not in _branch.split('} else {')[0])
check('a spent token is replaced immediately, or the next load would present '
      'a dead one', '_storeDeviceToken(r.token)' in JS)
check('a refused token is dropped rather than retried forever',
      '_clearDeviceToken();' in JS.split('async function _resumeFromDeviceToken')[1][:1400])
check('disconnecting clears it here too, or the next page load would sign the '
      'browser straight back in',
      '_clearDeviceToken();' in JS.split('function disconnectWallet')[1][:800])
check('every storage read and write is wrapped — private browsing throws on '
      'write, and remembering is a convenience, not a reason to break',
      JS.split('function _deviceToken')[1][:900].count('catch(e)') >= 3)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
