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

check('the logout result is read rather than discarded, since it is the only '
      'thing that makes reloading worth doing',
      '.ok' in branch and 'catch(()=>{})' not in branch)
check('...and a failed logout does not reload, because the next load would hit '
      'the same failure', '_cleared && !_tried' in branch)
check('the reload can happen at most once per tab, so even a mismatch that '
      'somehow survives a successful logout cannot spin',
      'sessionStorage.setItem' in branch
      and 'orca_wallet_mismatch_reload' in branch)
check('...and the marker is set BEFORE the reload, or it would never be read',
      branch.index('setItem') < branch.index('location.reload'))
check('storage is wrapped, since it throws outright in some private-browsing '
      'modes — a diagnostic must not become the fault',
      branch.count('try{') >= 2 and 'catch(e){}' in branch)

check('when it stops, it says why on screen rather than leaving a page that '
      'looks stuck', 'wallet-install-msg' in branch and 'textContent' in branch)
check('...naming what the person has to do, in the extension, not what the app '
      'saw',
      # Matched on the Dutch words until the app was translated. The check was
      # never about the language -- it is that the message names the extension
      # and asks for a reload, rather than reporting what the code noticed.
      'extension' in branch and 'reload this page' in branch)
check('...and leaves a console line with both facts, so the next person '
      'debugging this does not have to guess which half failed',
      'console.warn' in branch and 'logout ok:' in branch)

check('a clean load forgets the marker, so a genuine mismatch later in the '
      'same tab can still fix itself the quick way',
      "removeItem('orca_wallet_mismatch_reload')" in JS
      and JS.index("removeItem('orca_wallet_mismatch_reload')") > JS.index('_extPk !== phantomKey'))

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
