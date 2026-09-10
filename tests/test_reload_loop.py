"""A reload that repeats the step that failed is a loop, not a recovery.

WHAT WAS WRONG
On load, the app compares the wallet in the Flask session against the wallet
the browser extension is actually connected with. When they disagree it logs
out and reloads, so the cleared session takes effect. That reload was
unconditional, and the logout's failure was swallowed:

    await fetch('/api/logout', ...).catch(()=>{});
    window.location.reload();

If the session was not really cleared — the request failed, or the page came
back from cache — the next load saw the identical mismatch and reloaded
again. There is no exit from that: a page refreshing itself every second or
two, with nothing on screen saying why.

THE RULE
A reload may only be used to recover when the thing it depends on actually
happened, and it may only be tried once. A condition that survives a
successful fix is not something repetition can solve, so it is explained to
the person instead.

WHAT HAPPENED SINCE
The loop was first made safe -- read the logout result, reload at most once.
Then the mismatch stopped ending the session at all: opening the app inside
Phantom's own browser with a second account selected was enough to be signed
out, and the extension's current account has no bearing on anything, since
trades are signed server-side by the trading wallet.

With nothing to clear, there is nothing to reload for. So the loop is now
impossible by construction rather than by guard, which is the stronger
result, and this file checks for that instead -- plus the rule itself, which
still applies to every other reload in the app.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
JS = open(REPO + '/static/dashboard.js').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# The mismatch branch, from the comparison to its return.
m = re.search(r'if\(_extPk !== phantomKey\)\{(.*?)\n    \}\n  \}', JS, re.S)
branch = m.group(1) if m else ''
check('the wallet-mismatch branch is still there — the loop is fixed, not '
      'deleted, because a stale session really does need clearing', bool(branch))

# The loop cannot happen because the reload is gone, not because a marker
# stops the second one. Nothing here reloads, and nothing here ends a session,
# so there is no failed step for a reload to repeat.
check('the branch does not reload at all — the strongest form of "cannot '
      'loop" is having nothing to loop on', 'location.reload' not in branch)
check('...and does not end the session either, which is what the reload used '
      'to be for', 'api/logout' not in branch and 'api/session/clear' not in branch)
check('the one-shot marker is gone with the reload it guarded, rather than '
      'being left behind to be read by something later',
      'orca_wallet_mismatch_reload' not in JS)

check('when it stops, it says why on screen rather than leaving a page that '
      'looks stuck', 'wallet-install-msg' in branch and 'textContent' in branch)
check('...saying they are still signed in, since that is the part that would '
      'otherwise be guessed from a header showing another address',
      'still signed in' in branch)
check('...and leaves a console line naming both accounts, so the next person '
      'debugging this does not have to guess which is which',
      'console.warn' in branch and 'keeping the session' in branch)

# ── the same shape must not come back elsewhere ───────────────────────────
# Every other reload in this file is either user-initiated or guarded by the
# success of the request it depends on. This is what that looks like.
_swallowed = re.findall(r'catch\(\(\)=>\{\}\)[^\n]*\n\s*window\.location\.reload', JS)
check('no other reload in the file follows a swallowed failure', not _swallowed)
check('the disconnect path may reload unconditionally, because it sets the '
      'flag that makes the next load stop early rather than reach this check',
      "localStorage.setItem('orca_manual_disconnect','1')" in JS
      and "localStorage.getItem('orca_manual_disconnect')" in JS)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
