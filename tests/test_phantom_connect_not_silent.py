""""Connect Phantom" did nothing when Phantom wasn't installed.

Two bugs stacked on top of each other, both confirmed against the real
running app (launched via app_entry.py; a bare `import dashboard` skips
every install()-based feature, wallet onboarding included, and hides both
of these):

1. _applyPhantomDetection(), called while the (old, now-invisible)
   #onboard overlay's wallet buttons are being set up, overwrote
   #phantom-ob-btn's .onclick property to `window.open('https://phantom.app',
   ...)` whenever Phantom wasn't detected on desktop. A JS .onclick PROPERTY
   assignment replaces the onclick="" HTML ATTRIBUTE's compiled handler
   outright -- they are the same slot, not two separate listeners. The
   wallet-onboarding.js chooser's "Connect Phantom" option reaches this
   exact button programmatically (connectControl().click(), see
   mobile-connect-button.js's startConnect()) specifically to run
   connectWalletOnboard('phantom') and surface WHY it failed; with the
   overwrite in place, that never happened -- the click just tried (and,
   headless or popup-blocked, silently failed) to open a new tab, with
   zero feedback on the page a user is actually looking at.

2. Even when connectWalletOnboard('phantom') does run, its own
   "not detected" / "sign the request" / "connection rejected" messages
   are written into #wallet-install-msg -- a child of that same permanently
   display:none #onboard overlay. See test_no_onboard_flash.py and
   _guestConnect()'s own "never resurrect the old full-screen onboarding"
   comment for why it stays hidden. _showWalletMsg() mirrors the same
   message as a toast (via showLfToast(), already loaded on every page)
   whenever the real element isn't visible, so a failure the user is
   supposed to see is not written somewhere only the old, retired overlay
   would have shown it.
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


detect = fn('_applyPhantomDetection')
check('desktop-not-installed no longer hijacks the button away from '
      "connectWalletOnboard('phantom') -- it only relabels it",
      "phantomBtn.onclick=function(){ window.open(" not in detect)
check('...the mobile branch (a real, visible deep-link redirect, not a '
      'silent no-op) is untouched',
      "phantomBtn.onclick=function(){ _phantomMobileV1Connect(); };" in detect)

check('a helper mirrors wallet-connect messages as a toast when their real '
      'container is not visible',
      'function _showWalletMsg(' in JS and 'showLfToast(' in JS)

cwo = fn('connectWalletOnboard')
check('every message connectWalletOnboard shows -- not detected, no '
      'pubkey, sign-rejected, connection-failed -- goes through that '
      'helper, not a bare msgEl write a hidden container could swallow',
      cwo.count('_showWalletMsg(') == 4
      and 'msgEl.innerHTML=name' not in cwo
      and "msgEl.textContent='Could not get" not in cwo)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
import sys
sys.exit(0 if all(c for _, c in checks) else 1)
