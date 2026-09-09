"""Staying signed in inside an app added to the home screen.

WHY THIS IS DIFFERENT FROM AN ORDINARY LOGOUT
A standalone app cannot complete the Phantom deeplink: it opens the browser,
and the session lands there instead. The connect screen knows this — it can
only tell you to go and open the site in Safari. So losing a session in an
installed app is not an inconvenience, it is being locked out of it.

A passkey is the one credential that works inside it, and the whole flow has
been in this codebase all along behind a prompt nobody could reach:
#s-faceid-prompt sits inside Settings at display:none, and no line anywhere
sets it visible. It has never been shown to a single user.

TWO THINGS THAT HAD TO BE SERVER-SIDE
Whether a wallet has a passkey was read from localStorage — which an
installed app has its own copy of. Someone with a passkey registered in
Safari looked, from inside the app, exactly like someone with none, and the
client could not tell that apart from "not this context". The server can.

And detecting the installed app itself: on iOS, where this actually happens,
navigator.standalone is the property Safari has always set, while the
display-mode media query has not been reliable. Missing it reads as an
ordinary browser tab, and the app then offers a connection that cannot
complete.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
JS = open(REPO + '/static/dashboard.js').read()
PAGE = open(REPO + '/dashboard.html').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


# ── the server answers whether there is a way back in ─────────────────────
sess = fn('api_session')
check('the session answer says whether this wallet has a passkey',
      "'has_passkey': has_passkey" in sess)
check('...looked up by WALLET, not by a credential id out of localStorage — an '
      'installed app has its own storage and would always report none',
      'webauthn_credentials c JOIN users u' in sess
      and 'u.wallet_address=?' in sess)
check('...only for a genuinely authenticated session, since a read-only one '
      'has proved nothing', 'if wallet and not readonly' in sess)
check('...and a failed lookup answers "no idea" rather than nagging, because '
      'an error is not evidence that someone lacks a passkey',
      'has_passkey = False   # unknown' in sess)
check('...with the connection closed on every path', sess.count('finally:') >= 1
      and 'conn.close()' in sess)

# ── the prompt that was never shown ───────────────────────────────────────
check('there is now a prompt outside Settings, where someone will actually '
      'meet it', 'id="pk-banner"' in PAGE)
check('...driven by the server\'s answer rather than local storage',
      '_maybePromptPasskey(_me)' in JS and 'session.has_passkey' in JS)
check('...and only when the device can actually create one',
      'window.PublicKeyCredential' in JS.split('function _maybePromptPasskey')[1][:600])
check('...never for a session that is not signed in',
      'session.authenticated' in JS.split('function _maybePromptPasskey')[1][:400])

body = JS.split('function _maybePromptPasskey')[1][:1600]
check('inside an installed app the wording says what is actually at stake — '
      'that connecting a wallet does not work there',
      'does not work from an app on' in body.replace("'\n      + '", ''))
check('...and it is not dismissible forever there, because dismissing it is '
      'agreeing to be locked out later',
      '_passkeyBannerDismissed() && !standalone' in body)
check('...while in a normal browser it is a convenience and can be dismissed '
      'for good', "localStorage.setItem('orca_pk_prompt_off', '1')" in JS)

# ── detecting the installed app ───────────────────────────────────────────
check('an iOS home-screen app is detected by navigator.standalone as well as '
      'the media query — on iOS that is the property that has always worked',
      'window.navigator.standalone === true' in JS)
check('...and reading it is guarded, since the prompt is defined above the '
      'const that holds it and the dead zone would throw rather than skip',
      'try{ standalone = isStandalonePWA; }catch(e)' in JS)

# ── the setup call has to work from both surfaces ─────────────────────────
check('the existing setup function takes the button and message to report '
      'into, instead of guessing which surface called it',
      'async function _setupFaceID(opts)' in JS
      and 'opts.btn||document.getElementById' in JS)
check('...and the Settings prompt still works, since it passes nothing and '
      'falls back to its own elements',
      "document.getElementById('s-faceid-prompt-btn')" in JS)
check('...with the caller told when it succeeded, so the banner can take '
      'itself away', 'if(opts.onDone) opts.onDone()' in JS)

# ── it must not appear where it cannot help ───────────────────────────────
check('the banner starts hidden, and is only revealed once all of that has '
      'been checked', 'id="pk-banner" style="display:none' in PAGE)
check('its buttons are thumb-sized, since this is the screen someone meets '
      'right after signing in on a phone', PAGE.count('min-height:44px') >= 2)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
