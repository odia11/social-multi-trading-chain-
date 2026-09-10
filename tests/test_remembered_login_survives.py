"""A remembered login must survive everything except a real refusal.

WHAT WAS HAPPENING
People kept being signed out, and it kept coming back right after a deploy.

The remembered login (the device token in localStorage) is the ONLY thing
standing between a user whose session cookie is gone and the connect screen.
_resumeFromDeviceToken() in static/dashboard.js exchanged it for a session --
and deleted it, permanently, on any falsy result:

    var r = await fetch('/api/session/resume', {...})
              .then(function(x){ return x.json(); })
              .catch(function(){ return null; });     // <-- every failure
    if(r && r.ok && r.wallet){ ...; return r.wallet; }
    _clearDeviceToken();                              // <-- reached by all of them

That .catch() turned a request which never reached the server into a
"refusal". So the token was thrown away for:

  · the seconds a deploy takes to restart the app -- every release silently
    signed out whoever opened the app in that window
  · any flaky mobile moment: a lift, a tunnel, a dead spot
  · a 502/503 from nginx while restarting, or a 429 from the rate limiter

None of those say anything about the token. The next load would have worked
-- but the token was already gone, so it could not.

Reproduced in a real browser before fixing: with the request aborted
(connectionrefused), localStorage came back null.

There was a second way to lose it. The server ROTATES the token on every
redeem, so two tabs opening together both present the same one: the first is
served and stores the replacement, the second is told 401 for a token that
was valid a moment ago -- and cleared the replacement the first tab had just
stored. Reproduced against the running server: tab A got 200 and a new
token, tab B got 401.

THE FIX
Clearing now happens on exactly one signal -- the server itself answering
401, the only answer that means the token is dead -- and only while what is
in storage is still the token we sent, so a tab that has been overtaken by
another leaves the good replacement alone.

A real Disconnect must still clear it; that path is checked here too, since
a fix that made the token unclearable would be a worse bug than the one it
replaced.

All five behaviours were verified in a real browser against a running server
by executing the SHIPPED function (sliced out of dashboard.js, not a
hand-copied version): kept on abort, kept on 503, kept on 429, kept when a
second tab had rotated it, cleared when genuinely dead.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
JS = open(REPO + '/static/dashboard.js', encoding='utf-8').read()

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    """The body of a top-level async function, comments stripped -- so none of
    the checks below can pass by matching the prose that explains them."""
    i = JS.index('async function ' + name + '(')
    j = JS.index('\n}', i) + 2
    body = JS[i:j]
    body = re.sub(r'/\*.*?\*/', '', body, flags=re.DOTALL)
    body = re.sub(r'(?m)^\s*//.*$', '', body)
    return body


resume = fn('_resumeFromDeviceToken')

# ── 1. the token is never dropped on anything but an explicit 401 ─────────
clears = re.findall(r'([^\n]*_clearDeviceToken\(\)[^\n]*)', resume)
check('_resumeFromDeviceToken clears the remembered login in at most one '
      'place -- it is the users only way back in',
      len(clears) <= 1)
check('...and that one place is gated on the server answering 401, not on a '
      'falsy/missing response (which is what a dead network looks like)',
      len(clears) == 1 and re.search(r'status\s*===?\s*401', clears[0]))

check('a bare `_clearDeviceToken();` on its own line -- unconditional, the '
      'shape of the original bug -- is gone',
      not re.search(r'(?m)^\s*_clearDeviceToken\(\);\s*$', resume))

# ── 2. a request that never reached the server keeps the token ────────────
check('the fetch is awaited so its HTTP status is actually available, rather '
      'than being collapsed straight to .json() (which loses the status and '
      'cannot tell 401 from 503)',
      re.search(r'res\s*=\s*await\s+fetch\(', resume) is not None)

net_fail = re.search(r'\}catch\s*\(\s*e\s*\)\s*\{([^}]*)\}', resume)
check('a network-level failure returns early WITHOUT clearing -- offline, a '
      'tunnel, or the seconds a deploy takes to restart the server',
      net_fail is not None
      and '_clearDeviceToken' not in net_fail.group(1)
      and 'return' in net_fail.group(1))

# ── 3. the two-tab rotation race ─────────────────────────────────────────
check('before clearing, it re-reads storage and only clears while that still '
      'holds the token it sent -- otherwise another tab has already rotated '
      'it and the value in storage is the good replacement',
      len(clears) == 1
      and re.search(r'_deviceToken\(\)\s*===?\s*t', clears[0]))

# ── 4. a real Disconnect must STILL clear it ─────────────────────────────
i = JS.index('function disconnectWallet(')
disconnect = JS[i:JS.index('\n}\n', i)]
check('disconnectWallet() still clears the remembered login -- a fix that '
      'made the token unclearable would be the worse bug',
      '_clearDeviceToken()' in disconnect)

# ── 5. nothing else anywhere may quietly drop it ─────────────────────────
all_clear_sites = [l for l in JS.split('\n')
                   if '_clearDeviceToken()' in l and 'function _clearDeviceToken' not in l]
check('the remembered login is cleared in exactly two places in the whole '
      'app: the guarded 401 branch, and Disconnect',
      len(all_clear_sites) == 2)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
