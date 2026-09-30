"""Tokens launched on OrcAgent are bought on OrcAgent.

A buy through OrcAgent earns the platform its 0.75% and the creator their
share of creator fees, so every way to a launched token leads to one short
OrcAgent link, /token/<mint>, which opens the token's card in Live Market:
- the public launch directory: a "Buy on OrcAgent" button, a Share button
  that shares that link, and the rewards line with the platform fee;
- the creator's own launch list: "Buy / Sell on OrcAgent" and "Share token
  link" (nothing links to another app's page to trade);
- Live Market: a "New on OrcAgent" rail of the newest launches; a tap
  opens the token in place, and the rail is absent when there are none.
"""
import os, re, sqlite3, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

mint, creator = str(Keypair().pubkey()), str(Keypair().pubkey())
now = int(time.time())
with sqlite3.connect(d.DB_FILE) as c:
    c.execute("INSERT INTO token_launches (id, wallet, client_nonce, name, symbol, icon_webp, reward_mode, quote_asset, "
              "status, mint, launch_signature, created_at, finalized_at, orcagent_bps) "
              "VALUES ('L1', ?, 'n1', 'Orca Test', 'ORCT', x'00', 'creator', 'USDC', 'live', ?, ?, ?, ?, 2000)",
              (creator, mint, '5' * 88, now - 3600, now - 3500))
cl = app.test_client(); B = 'https://orcagent.fun'
data = cl.get('/api/token-launches?page=1', base_url=B).get_json()
row = data['launches'][0]
check('the directory hands out one short OrcAgent link per launched token',
      row['mint'] == mint and row['trade_url'] == '/token/' + mint and row['orcagent_bps'] == 2000)
r = cl.get('/token/' + mint, base_url=B)
check('...which opens that token\'s card in Live Market, where the buy runs through OrcAgent',
      r.status_code == 302 and r.headers['Location'].endswith('/live-market?mint=' + mint + '&profile=1'))

dir_js = read('static', 'token-launches.js')
check('directory cards lead with "Buy on OrcAgent" on that link',
      "var buy=dom('a','buy','Buy on OrcAgent');buy.href=tradeUrl;" in dir_js
      and "data.trade_url||('/token/'+encodeURIComponent(data.mint))" in dir_js)
check('...and a Share button that shares the OrcAgent link (native share sheet, else copy)',
      "shareToken(data,tradeUrl,shareBtn)" in dir_js and 'var url=location.origin+path' in dir_js
      and 'navigator.share' in dir_js and 'navigator.clipboard.writeText(text+' in dir_js)
check('...and the rewards line shows the platform fee instead of "100% creator"',
      "' platform fee'" in dir_js and "'100% creator'" not in dir_js)
check('the directory\'s Buy button spans the card (the main action on a phone)',
      '.actions a.buy{flex:1 1 100%' in read('templates', 'token_launches.html'))

launch_js = read('static', 'token-launch.js')
check("the creator's own live token offers Buy / Sell on OrcAgent and a Share token link",
      "dom('a','tl-buy-sell','Buy / Sell on OrcAgent');trade.href=tokenPath(row.mint)" in launch_js
      and "dom('button','tl-share-token','Share token link')" in launch_js
      and "function tokenPath(mint){return '/token/'+encodeURIComponent(mint)}" in launch_js)
check('...and nothing there links straight to a market page with a bare mint any more',
      "'/live-market?mint='" not in launch_js and "'/live-market?mint='" not in dir_js)

lm_html = read('templates', 'live_market_pro.html'); lm = read('static', 'live-market-pro.js')
check('Live Market shows a "New on OrcAgent" rail, linking to all launches',
      'id="pt-launch-wrap" style="display:none"' in lm_html and 'NEW ON ORCAGENT' in lm_html
      and 'href="/launches">All launches' in lm_html)
card = lm[lm.index('function launchCardHtml'):lm.index('function loadLaunches')]
check('...whose cards open the token in place, through the same path a surging token uses',
      'data-action="open-surge" data-mint="\'+esc(l.mint)+\'" data-symbol="\'+esc(l.symbol)+\'"' in card)
loader = lm[lm.index('function loadLaunches'):lm.index('function loadSurges')]
check('...fed from the launch directory, and hidden when there is nothing launched',
      "fetch('/api/token-launches?page=1'" in loader and "wrap.style.display='none'" in loader
      and "_railsBeingTouched['pt-launch-rail']" in loader)
check('...loaded with the page, on pull-to-refresh, and every minute while visible',
      lm.count('loadLaunches();') >= 2 and 'if(!document.hidden) loadLaunches(); }, 60000);' in lm
      and "enableDragScroll(document.getElementById('pt-launch-rail'));" in lm)
check('...and out of the way in a token\'s profile view',
      'body.pt-profile-mode .pt-launch-wrap' in lm_html)
raise SystemExit(0 if all(checks) else 1)
