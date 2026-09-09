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

# ── 3. the account-mismatch guard clears, it does not revoke ──────────────
mismatch = JSC[JSC.index('_extPk !== phantomKey'):][:900]
check('the account-mismatch guard signs this browser out without revoking '
      'remembered logins — nobody pressed Disconnect, somebody switched '
      'accounts, and that must not sign them out on every other device',
      'api/session/clear' in mismatch and 'api/logout' not in mismatch)

check('that endpoint exists on the server', "'/api/session/clear'" in SRC)
clear_fn = fn('api_session_clear')
check('...and it clears the session', 'session.clear()' in clear_fn)
check('...while leaving every remembered login alone, which is the entire '
      'difference between it and logout',
      '_revoke_device_tokens' not in clear_fn)
check('...whereas Disconnect DOES revoke them, on every device',
      '_revoke_device_tokens' in fn('logout'))

# The distinction has to be structural. A single endpoint taking "revoke:
# false" from the page would be a page that can be made to ask for that.
logout_fn = fn('logout')
check('neither endpoint takes the decision from the page — no flag in the '
      'request body decides whether remembered logins survive',
      not re.search(r'request\.(json|form|args)', logout_fn + clear_fn))

# ── 4. the cookie itself outlives the visit ───────────────────────────────
check('every login makes the session cookie permanent, so closing the tab is '
      'not a logout',
      SRC.count('session.permanent') >= SRC.count("session['wallet'] ="))
life = re.search(r"PERMANENT_SESSION_LIFETIME'\]\s*=\s*timedelta\(days=(\d+)\)", SRC)
check('...and it lasts weeks rather than hours', life and int(life.group(1)) >= 14)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
