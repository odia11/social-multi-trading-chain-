"""A first-time guest could not connect a wallet on desktop.

Desktop's home shell (static/home-desktop.js, see its own commit) renders
the full app -- sidebar, feed, portfolio -- for a disconnected guest too,
rather than gating on #onboard the way the page used to. The only path back
in is the small "Connect wallet" link in the top-right (onclick=
_guestConnect()). _checkTipsOnLoad() opened a full-screen, backdrop-blurred
"trading tips" tour 600ms after ANY page load where localStorage had no
orcagent_tips_seen key -- with no check for whether anyone was signed in.
For a guest who had never seen it, that tour opened right on top of the
page and sat there, its backdrop intercepting every click including the
one on "Connect wallet" -- confirmed against the real running app: the
modal's own backdrop divs blocked pointer events to everything behind them,
and the tour is meaningless to someone who has not connected anything yet
to run a "here's what your bot does" trade-tips carousel for.
"""
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(REPO + '/static/dashboard.js', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    i = JS.index('function ' + name + '(')
    j = JS.index('\n}', i) + 2
    return JS[i:j]


check('the tips tour only opens for someone actually signed in',
      'window.__SESSION_WALLET' in fn('_checkTipsOnLoad'))
check('...and still only once per browser, same as before',
      "localStorage.getItem('orcagent_tips_seen')" in fn('_checkTipsOnLoad'))
check('...checking sign-in state before the localStorage flag, not after -- '
      'a guest is never even asked whether they have seen it',
      fn('_checkTipsOnLoad').index('window.__SESSION_WALLET')
      < fn('_checkTipsOnLoad').index('orcagent_tips_seen'))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
import sys
sys.exit(0 if all(c for _, c in checks) else 1)
