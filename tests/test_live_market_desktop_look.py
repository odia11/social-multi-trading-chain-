"""Live Market on desktop looks like the rest of the app and states sizes right.

- Colours: the phone card design (live-market-redesign/final.css) paints the
  canvas, panels and cards navy (#071019 / #0b1117 / #1a232d), while the
  menu bar above and every other page are charcoal (#0a0b0e). Desktop now
  uses the charcoal of the menu bar; phones keep their card design.
- Live Trades rail: sizes in dollars. Buys read "0.000 SOL" when a position
  had no recorded spend, and USDC trades were labelled "SOL".
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

html = read('templates', 'live_market_pro.html')
desk = html[html.index('@media(min-width:768px){\nbody{--oa-canvas'):]
desk = desk[:desk.index('\n}\n')]
check('desktop overrides the navy canvas, panels, cards and lines with the menu-bar charcoal',
      all(v in desk for v in ('--oa-canvas:#0a0b0e', '--oa-surface:#0d0f12', '--oa-surface2:#101216',
                              '--oa-panel:#0d0f12', '--oa-panel2:#101216', '--oa-line:#1c2027',
                              '--oa-line2:#21252c', '--oa-border:#1c2027')))
check('...which is the menu bar\'s own colour',
      '--bg:#0a0b0e' in html and 'background:#0a0b0e' in read('static', 'navbar.css').replace(' ', '')
      or '#0a0b0e' in read('static', 'navbar.css'))
check('...the Profile button and chart note follow it, and phones keep their card design',
      '.pt-profile-btn{border-color:#2a2f37;background:#16191f}' in desk
      and '.pt-chart-waiting{background:#0d0f12cc}' in desk
      and '--oa-canvas:#071019' in read('static', 'live-market-final.css'))

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
now = time.time()
c = sqlite3.connect(d.DB_FILE)
c.execute("INSERT INTO open_positions (user_id, mint_address, symbol, amount, buy_price, opened_at, source, chain, base_currency) "
          "VALUES (?, 'm1', 'NOSPEND', 1000, 0.00094, ?, 'bot', 'solana', 'USDC')", (uid, now - 60))
for tok, amt, px, side, base, ago in (('USDCSELL', 10, 0.3256, None, 'USDC', 120), ('SOLSELL', 2, 0.5, None, 'SOL', 180),
                                      ('BUYLEG', 5, 1.0, 'buy', 'USDC', 30)):
    c.execute("INSERT INTO trades (user_id, token, entry_price, exit_price, amount, pnl, source, side, chain, base_currency, timestamp) "
              "VALUES (?,?,?,?,?,0,'bot',?,'solana',?, datetime('now', ?))", (uid, tok, px, px, amt, side, base, '-%d seconds' % ago))
c.commit(); c.close()
d._sol_price_usd = 150.0
rows = {r['symbol']: r for r in app.test_client().get('/api/market/tape', base_url='https://orcagent.fun').get_json()['trades']}
check('a buy without a recorded spend shows the position\'s size, not 0',
      rows['NOSPEND']['side'] == 'buy' and rows['NOSPEND']['usd_amount'] == 0.94)
check('a USDC sell is its dollar size; a SOL-mode sell is converted at the SOL price',
      rows['USDCSELL']['usd_amount'] == 3.26 and rows['SOLSELL']['usd_amount'] == 150.0)
check('a single buy leg is not listed as a SELL', 'BUYLEG' not in rows)
js = read('static', 'live-market-pro.js')
check('the rail shows dollars (SOL only for an old server reply)',
      "(r.usd_amount!=null?'$'+Number(r.usd_amount).toFixed(2):Number(r.sol_amount||0).toFixed(3)+' SOL')" in js)
raise SystemExit(0 if all(checks) else 1)
