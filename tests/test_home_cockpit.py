"""Signed-in Home opens on a cockpit, not a marketing hero.

The hero ("Smarter Trading. Stronger Together.") pitches OrcAgent to someone
who has not joined; its four icons do nothing. A signed-in trader instead
gets, at the top of mobile Home:
- their portfolio value (tap: Portfolio) and four actions that each do
  something: Deposit (opens the deposit sheet), Trade, Launch, Call (opens
  the call sheet);
- what is moving now: "Surging now" and "New on OrcAgent" rails, each
  hidden when empty and refreshed with pull-to-refresh and every minute;
- then the AI Bot card, the markets and the feed.
Guests keep the hero and the shortcut row.
"""
import os, re, subprocess
ROOT = os.path.join(os.path.dirname(__file__), '..')
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

js = read('static', 'home-mobile.js')
init = js[js.rindex('ready(function(){'):]
check('signed-in is known before anything is built (the session wallet the server embeds)',
      "function signedIn(){var w=window.__SESSION_WALLET;return !!(w&&w!=='__SESSION_WALLET__')}" in js
      and "window.__SESSION_WALLET = '__SESSION_WALLET__';" in read('dashboard.html'))
check('a signed-in member gets the cockpit, the opportunities, the bot and the markets -- no hero',
      'if(signedIn()){var today=buildToday(wrap),opps=buildOpps(today),bot=buildBot(wrap,opps),market=buildMarkets(bot)' in init
      and 'buildHero' not in init.split('}else{')[0])
check('...while a guest keeps the hero and the shortcut row',
      'var hero=buildHero(wrap)' in init.split('}else{')[1] and 'buildShortcuts(' in init.split('}else{')[1])

today = js[js.index('function buildToday'):js.index('function oppAge')]
check('the cockpit shows the portfolio value (same live/cached painter as before) and links to Portfolio',
      '<strong id="oa-m-pf-value">' in today and 'href="/wallet"' in today and 'startPortfolio();' in today)
check('...and four actions that each do something',
      'href="/wallet#deposit"' in today and 'href="/live-market"' in today
      and 'href="/token-launch"' in today and "window._openCallSheet()" in today)
check('Deposit opens the deposit sheet on Portfolio (and drops the hash)',
      "location.hash!=='#deposit'||typeof _modalDeposit!=='function'" in read('templates', 'wallet.html')
      and "history.replaceState(null,'',location.pathname+location.search)" in read('templates', 'wallet.html'))

opps = js[js.index('function buildOpps'):js.index('/* ') if False else js.index('function loadOpps')]
load = js[js.index('function loadOpps'):]
load = load[:load.index('\n}\n')]
check('"Surging now" and "New on OrcAgent" rails, each hidden until it has something',
      'id="oa-m-surge" hidden' in opps and 'id="oa-m-launches" hidden' in opps
      and "fetch('/api/market/surges'" in load and "fetch('/api/token-launches?page=1'" in load
      and load.count('box.hidden=!list.length') == 2)
check('...a surging token opens its card in Live Market, a launch via its OrcAgent link',
      "'/live-market?mint='+encodeURIComponent(s.mint)+'&profile=1'" in load
      and "l.trade_url||('/token/'+encodeURIComponent(l.mint))" in load)
check('...token names are escaped before they reach the page',
      "function esc(v){" in js and "<b>$'+esc(sym)+'</b>" in js and "esc(img)" in js and "esc(l.quote_asset)" in js)
check('...refreshed on pull-to-refresh and every minute while visible',
      "document.getElementById('oa-m-opps')?loadOpps():null" in js
      and 'OrcPageLifecycle.setInterval(function(){if(!document.hidden)loadOpps()},60000);' in opps)

css = read('static', 'home-mobile.css')
check('the cockpit has its own styles (four equal actions, Deposit as the primary)',
      'body.oa-home-mobile .oa-m-actions{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))' in css
      and 'body.oa-home-mobile .oa-m-actions .primary{background:#f7b955' in css)
check('phones fetch the new Home files (versions bumped everywhere)',
      all('home-mobile.js?v=15' in read(*f) and 'home-mobile.css?v=14' in read(*f)
          for f in (('static', 'navbar.js'), ('static', 'app-ux.js')))
      and 'home-mobile.css?v=14' in read('app_performance.py'))
r = subprocess.run(['node', '-e', 'new Function(require("fs").readFileSync(0,"utf8"))'], input=js,
                   capture_output=True, text=True, timeout=20)
check('home-mobile.js still parses', r.returncode == 0)
raise SystemExit(0 if all(checks) else 1)
