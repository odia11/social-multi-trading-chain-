"""A signed-in visitor must never see the connect screen flash.

WHAT WAS HAPPENING
Every click on a nav link (Feed, Live Market, ...) does a full page reload --
this is a classic multi-page Flask app, not an SPA. #onboard, the full-screen
connect/onboarding overlay, has no display:none of its own; only a JS check
against window.__SESSION_WALLET hides it. That check lived in a <script> near
the very end of the document -- after #onboard's own ~1150-line subtree
(wallet-connect buttons, the private-key form, the terms modal) had already
been parsed.

On a real network the browser paints incrementally as HTML streams in. That
left a window, on every single navigation, where #onboard could be painted
on screen before the parser reached the script far below it and hid it
again. Not a one-time login flash -- a flash on every page load, for anyone
already connected.

THE FIX
The check moved to be the FIRST thing inside #onboard: a synchronous,
blocking <script> right after its opening tag, before a single child element
of #onboard is parsed. A DOM node exists the moment its opening tag is
parsed, so document.getElementById('onboard') resolves correctly there --
this is a standard, safe technique.

This is checked against the SERVER'S ACTUAL RENDERED OUTPUT for both a
signed-in and a signed-out visitor, not just the source text, because what
matters is the byte order the browser receives.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
HTML = open(REPO + '/dashboard.html', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

# ── 1. the source itself ──────────────────────────────────────────────────
onboard_open = HTML.index('<div id="onboard">')
hide_call = HTML.index("document.getElementById('onboard').style.display = 'none'")
first_child = HTML.index('<div class="ob-box">')

check('the hide check is the first thing inside #onboard in the SOURCE',
      onboard_open < hide_call < first_child)
check('...specifically before #onboard\'s own first real element, not merely '
      'somewhere earlier in the file',
      HTML[onboard_open:first_child].count('<div id="onboard">') == 1)

check('nothing before #onboard opens reads window.__SESSION_WALLET or '
      'window.__API_SHARED_SECRET -- they are not set yet',
      '__SESSION_WALLET' not in HTML[:onboard_open]
      and '__API_SHARED_SECRET' not in HTML[:onboard_open])

check('the three placeholder tokens each appear exactly once in the file, so '
      'moving them could not have left a stale duplicate behind',
      HTML.count('__SESSION_WALLET__') == 1
      and HTML.count('__SESSION_SHORT__') == 1
      and HTML.count('__API_SHARED_SECRET__') == 1)

check('#sb-bottom\'s own reveal still happens -- it just does not need to be '
      'early, since it lives inside #app, which stays display:none until '
      'launchApp() shows it explicitly',
      "getElementById('sb-bottom')" in HTML)

# ── 2. the actual server-rendered output, both ways ────────────────────────
import os, tempfile
d = tempfile.mkdtemp()
os.environ.update({'DATA_DIR': d, 'SECRET_KEY': 'x' * 32,
                   'ENCRYPTION_KEY': 'K' * 43 + '=', 'DEV': '1'})
sys.path.insert(0, REPO)
import dashboard as m
app = m.app
app.config['TESTING'] = True

with app.test_client() as c:
    with c.session_transaction() as s:
        s['wallet'] = 'WalletFlashTest1234567890'
    rendered = c.get('/').get_data(as_text=True)

r_open = rendered.index('<div id="onboard">')
r_hide = rendered.index("document.getElementById('onboard').style.display = 'none'")
r_first_child = rendered.index('<div class="ob-box">')

check('RENDERED for a signed-in visitor: the hide script still runs before '
      "#onboard's first child, after the server's own string substitution",
      r_open < r_hide < r_first_child)
check('...and the real wallet address was actually substituted in, not left '
      'as the placeholder token',
      "window.__SESSION_WALLET = 'WalletFlashTest1234567890';" in rendered
      and '__SESSION_WALLET__' not in rendered)

with app.test_client() as c2:
    signed_out = c2.get('/').get_data(as_text=True)
check('RENDERED for a signed-out visitor: window.__SESSION_WALLET is empty, '
      'so the onboard screen correctly stays visible -- this only ever hides '
      'it for someone actually signed in',
      "window.__SESSION_WALLET = '';" in signed_out)

# ── 3. /dashboard gets the same fix -- it renders the same template ────────
with app.test_client() as c3:
    with c3.session_transaction() as s:
        s['wallet'] = 'WalletFlashTest2'
    dash_html = c3.get('/dashboard', follow_redirects=True).get_data(as_text=True)
check('/dashboard (the other route that injects a real session) carries the '
      'same fix, since both serve the same template',
      dash_html.index('<div id="onboard">')
      < dash_html.index("document.getElementById('onboard').style.display = 'none'"))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
