"""Nothing signs a person out except the person.

WHAT WAS HAPPENING
The page ran its own inactivity timer: a warning at 8 minutes, an automatic
logout at 10. Read the feed, put the phone down, come back after lunch --
signed out, and sent back to Phantom for a signature already given. On a
phone that is most sessions, and backgrounding the app counted as idle, so
the countdown meant to warn you never got the chance.

It is gone. A session ends when Disconnect is pressed.

THE ONE EXCEPTION, AND WHY IT IS NOT A LOGOUT
If the wallet extension is sitting on a different account than the session
belongs to, the page signs ITSELF out -- otherwise the app shows one
account's balances while the wallet would sign for another. Nobody pressed
anything there, so it must not revoke the remembered logins: somebody
switched accounts, nothing was stolen. That is a different endpoint, and
which one revokes is decided on the server by the URL rather than by a flag
the page sends.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
JS = open(REPO + '/static/dashboard.js').read()
NAVJS = open(REPO + '/static/navbar.js').read()
HTML = open(REPO + '/dashboard.html').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

# The removal is explained at length in comments, and every term below appears
# in that prose. Matching against it would be matching against my own writing.
def code(js):
    out, in_block = [], False
    for line in js.split('\n'):
        t = line.strip()
        if in_block:
            if '*/' in t: in_block = False
            continue
        if t.startswith('/*'):
            in_block = '*/' not in t
            continue
        if t.startswith('//'):
            continue
        out.append(re.sub(r'//.*$', '', line))
    return '\n'.join(out)

JSC = code(JS)

# ── 1. there is no timer that can sign anyone out ─────────────────────────
for name in ('INACT_LIMIT_MS', 'INACT_WARN_MS', '_checkInactivity',
             '_lastActivity', '_showInactWarning', 'stayConnected'):
    check(f'the inactivity machinery is gone, not merely disabled: {name}',
          name not in JS)
check('...including the countdown popup, so no dead markup is left telling '
      'people they are about to be logged out', 'inact' not in HTML)

# Anything on a timer that ends a session is the bug coming back, whatever
# it gets named next.
timed = re.findall(r'set(?:Interval|Timeout)\s*\(\s*([A-Za-z_$][\w$]*)', JSC)
check('nothing that signs a person out runs on a timer at all',
      not any(n in ('doLogout', 'disconnectWallet', '_doLogout') for n in timed))
check('...and no timer calls the logout endpoint directly either',
      not re.search(r'set(?:Interval|Timeout)\s*\([^)]*api/logout', JSC))

# ── 2. the only session-ending paths are the ones a person triggers ───────
callers = [l.strip() for l in JSC.split('\n') if 'api/logout' in l]
check('the logout endpoint is called from exactly one place in the app — the '
      'Disconnect button', len(callers) == 1)
check('...and the navbar Disconnect goes through that same function rather '
      'than calling logout on its own path',
      'disconnectWallet' in NAVJS)

# The other silent sign-out: POSTing an empty address clears the session
# server-side. It must not be reachable from anything automatic.
empties = [l.strip() for l in JSC.split('\n')
           if "api/wallet/set'" in l and "address:''" in l]
check('the only calls that clear the wallet server-side by posting an empty '
      'address sit in deliberate user actions, not in any timer or watcher',
      len(empties) == 2)      # doLogout, and stepping back in onboarding

# ── 3. a different account in the wallet is not a logout ──────────────────
# This guard used to clear the session and reload when the extension sat on a
# different account than the session. Nobody pressed anything: opening the app
# inside Phantom's own browser with a second account selected was enough to be
# thrown out. And it guarded almost nothing -- the extension signs only the
# login message and a promotion payment; trades are signed server-side by the
# trading wallet, which has nothing to do with the account the extension shows.
mismatch = JSC[JSC.index('_extPk !== phantomKey'):][:1100]
check('a mismatched account in the wallet does NOT end the session — it was '
      'the last thing left that signed somebody out without being asked',
      'api/session/clear' not in mismatch
      and 'api/logout' not in mismatch
      and 'location.reload' not in mismatch)
check('...it is said out loud instead, so the person is not left wondering '
      'why the header shows another address',
      'wallet-install-msg' in mismatch and 'still signed in' in JS)
# Read from the comment-stripped source. The comment here says "Deliberately
# no return", so searching the raw text finds the word `return` in the
# sentence explaining that there isn't one. Fifth time this suite has read its
# own prose; it will not be the last, so: strip first, then match.
# Bounded by where the block actually ends -- the next statement is the
# ordinary `if(phantomKey){ await launchApp(); return; }`, whose return is
# correct and has nothing to do with this guard. A fixed character window ran
# straight past the closing brace and read it.
_mm_code = JSC[JSC.index('_extPk !== phantomKey'):]
_mm_code = _mm_code[:_mm_code.index('await launchApp()')]
check('...and the app carries on rather than stopping there',
      'return' not in _mm_code)

check('the endpoint that existed only for that guard is gone with it, rather '
      'than sitting there unused with the power to end a session',
      '/api/session/clear' not in SRC)

logout_fn = fn('logout')
check('Disconnect revokes every remembered login, on every device',
      '_revoke_device_tokens' in logout_fn)
check('...and does not take that decision from the page — no flag in the '
      'request body decides whether remembered logins survive',
      not re.search(r'request\.(json|form|args)', logout_fn))

# ── 4. the cookie itself outlives the visit ───────────────────────────────
check('every login makes the session cookie permanent, so closing the tab is '
      'not a logout',
      SRC.count('session.permanent') >= SRC.count("session['wallet'] ="))
life = re.search(r"PERMANENT_SESSION_LIFETIME'\]\s*=\s*timedelta\(days=(\d+)\)", SRC)
check('...and it lasts weeks rather than hours', life and int(life.group(1)) >= 14)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
