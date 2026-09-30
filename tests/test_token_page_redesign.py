"""Live Market's token page (profile mode) as a proper page.

The open token card used to be the feed card with a "Close" button, the
feed's filters above it, bare dashes for everything unknown, a chart note
lying over the time axis, a "0 friends · 0 txns · —" row, and Buy as the
outline button next to a gold Sell, halfway down the page. Now, for the
open card only (feed cards are unchanged, and restored when it closes):
- a back ("Live Market") / share / watchlist bar; filters and "Close" hidden;
- "New · no 24h change yet" instead of a bare dash, empty market data in
  words ("No trades yet", "Not reported yet");
- the gold chart stays; its first-price note sits clear of the axis;
- Your position (value, P&L, amount, avg buy price, paid) when held -- the
  holding API now reports entry price and cost for a tracked position;
- Safety checks, "On OrcAgent" (people you follow / traders holding), and
  About with creator links (http(s) only), Copy and Solscan;
- Buy (gold, main) / Sell (secondary, off when nothing is held), pinned
  above the menu on phones.
"""
import os, re, sys, tempfile, subprocess
from unittest.mock import patch
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
js = read('static', 'live-market-pro.js'); html = read('templates', 'live_market_pro.html')

# the holding API: entry price and cost for a tracked position
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
mint = str(Keypair().pubkey())
d.get_user_state(w)['positions'][mint] = {'amount': 2_500_000.0, 'buy_price': 0.0000036, 'spend': 9.0,
                                          'chain': 'solana', 'base_currency': 'USDC', 'symbol': 'TST'}
cl = app.test_client(); B = 'https://orcagent.fun'
with cl.session_transaction(base_url=B) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = 'x' * 40
with patch.object(d, 'get_token_data', return_value={'price': 0.000004, 'symbol': 'TST'}):
    h = cl.get('/api/trade/holding?chain=solana&token_address=' + mint, base_url=B).get_json()
check('the holding API reports what was paid for a tracked position',
      h['ok'] and h['amount'] == 2_500_000.0 and h['entry_price_usd'] == 0.0000036 and h['cost_usd'] == 9.0)
other = str(Keypair().pubkey())
with patch.object(d, 'get_token_data', return_value=None), patch.object(d, '_solana_token_amount', return_value=0.0):
    h2 = cl.get('/api/trade/holding?chain=solana&token_address=' + other, base_url=B).get_json()
check('...and nothing (never a guess) when there is no tracked position',
      h2['entry_price_usd'] is None and h2['cost_usd'] is None)

sync = js[js.index('function syncTokenProfile(){'):js.index('function loadTokenProfileDetails(')]
check('opening the page mounts it, closing restores the feed card',
      '_pfMount(card,ST.tokens[idx])' in sync and 'if(!chosen) _pfUnmount(card);' in sync)
check('a back / share / watchlist bar replaces "Close"; filters are hidden',
      "_pfNode('button', 'pt-pf-back', 'Live Market')" in js and "back.dataset.action = 'token-profile'" in js
      and 'body.pt-profile-mode .pt-feed-hd,body.pt-profile-mode #oa-lm-quick{display:none!important}' in html
      and 'body.pt-profile-mode .pt-card.pt-profile-open .pt-card-hd-right,' in html)
check('empty market data says so in words, a missing 24h change says "New"',
      "var _PF_EMPTY = {liq: 'Not reported yet', vol: 'No trades yet', ratio: 'No trades yet', mcap: 'Not reported yet'};" in js
      and "content:attr(data-empty)" in html and "content:'New · no 24h change yet'" in html)
check("the gold chart stays; its first-price note no longer lies over the axis",
      "waiting.textContent='First price is in · the chart draws itself as this token trades';" in js
      and 'Live price available · waiting for a second price observation' not in js
      and '.pt-chart-waiting{left:50%!important' in html)
check('Your position shows value, P&L, amount, avg buy price and paid when held',
      all(x in js for x in ("'Your position'", "'Value now'", "cell('You hold'", "cell('Avg buy price'", "cell('You paid'")))
check('Safety checks, On OrcAgent and About (Copy, Solscan, creator links http(s) only)',
      "'Safety checks'" in js and "'No one you follow holds this yet'" in js and "'Trades on OrcAgent show up here'" in js
      and "copy.className='pt-pf-copy'" in js and "if(!isSafeUrl(url)) return;" in js and "link(info.telegram_url,'Telegram')" in js)
check('Buy is the gold main action, Sell secondary and off when nothing is held',
      "if(sell){ sell.disabled = !held;" in js and "sell.title = \"You don't hold this token\"" in js
      and ".pt-profile-open .pt-buy-btn{order:2;background:linear-gradient(180deg,#ffd26a,#f7b43f)!important" in html)
check('on phones Buy/Sell is pinned above the menu, clear of the POST button',
      'bottom:calc(72px + env(safe-area-inset-bottom,0px));z-index:1100;padding:12px 16px 36px!important' in html)
check('the token info API also returns website and Telegram links',
      "'telegram_url':      telegram," in read('dashboard.py') and "'website_url':       website," in read('dashboard.py'))
r = subprocess.run(['node', '--check', os.path.join(ROOT, 'static', 'live-market-pro.js')], capture_output=True, text=True)
check('live-market-pro.js parses', r.returncode == 0)
raise SystemExit(0 if all(checks) else 1)
