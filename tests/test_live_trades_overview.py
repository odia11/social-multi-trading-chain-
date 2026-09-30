"""Live Trades shows what the bot bought and sold, with entry and exit.

- Open positions: every token the bot holds right now -- the scanner bot and
  the Narrative agent alike -- with entry, the current price, stake and
  result. A manual or copy trade is not the bot's and is not listed.
- A held token that has left the scanner list still gets its real price
  (the one the bot's own stop-loss monitor reads); a price that cannot be
  read shows as unknown, never as a flat 0% at the entry price.
- Bot trades: the bot's finished round trips, newest first -- bought at,
  sold at, result in dollars and percent, why it sold, how long it held.
  Manual trades and single buy/sell legs are not in it.
- "Ready" is the capital the bot trades with (USDC), not the SOL fee balance.
- The page renders from the same data the poll returns, in English.
"""
import os, sqlite3, sys, tempfile, time
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

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
BOT, NARR, MAN, GONE = (str(Keypair().pubkey()) for _ in range(4))
now = time.time()
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
for mint, sym, price, src, ago in ((BOT, 'BOTTOK', 0.002, 'bot', 600), (NARR, 'NARR', 0.5, 'narrative', 1200),
                                   (MAN, 'MANUAL', 1.0, 'manual', 60), (GONE, 'GONE', 0.01, 'bot', 90)):
    c.execute('INSERT INTO open_positions (user_id, mint_address, symbol, amount, buy_price, opened_at, source, chain, base_currency) '
              'VALUES (?,?,?,?,?,?,?,?,?)', (uid, mint, sym, 1000, price, now - ago, src, 'solana', 'USDC'))
rows = [  # token, entry, exit, amount, pnl(USDC), source, side, reason, hold
    ('WIN', 0.001, 0.0015, 10000, 5.0, 'bot', None, 'TAKE PROFIT +50.0%', 1800),
    ('LOSS', 0.02, 0.018, 500, -1.0, 'narrative', None, 'STOP LOSS -10.0%', 240),
    ('HAND', 1.0, 2.0, 1, 1.0, 'manual', None, None, 60),
    ('LEG', 1.0, 1.0, 1, 0.0, 'bot', 'buy', None, 0),
]
for tok, e, x, a, pnl, src, side, reason, hold in rows:
    c.execute('INSERT INTO trades (user_id, token, entry_price, exit_price, amount, pnl, source, side, exit_reason, hold_seconds, chain, base_currency, opened_at) '
              "VALUES (?,?,?,?,?,?,?,?,?,?, 'solana', 'USDC', ?)", (uid, tok, e, x, a, pnl, src, side, reason, hold, now - hold - 30))
c.commit(); c.close()

d.state['tokens'] = [{'mint': BOT, 'price': 0.0025}, {'mint': NARR, 'price': 0.4}]
def fake_token(mint, fast=False, chain=None):
    return {'price': 0.012} if mint == GONE else None

cl = app.test_client(); B = 'https://orcagent.fun'
with cl.session_transaction(base_url=B) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = 'x' * 40
with patch.object(d, 'get_token_data', side_effect=fake_token):
    api = cl.get('/api/live-trades', base_url=B).get_json()
pos = {p['token']: p for p in api['positions']}
check('open positions list what the scanner bot and the Narrative agent hold, not manual trades',
      set(pos) == {'BOTTOK', 'NARR', 'GONE'})
check('...each with entry, current price, stake and result',
      pos['BOTTOK']['entry_price'] == 0.002 and pos['BOTTOK']['current_price'] == 0.0025
      and pos['BOTTOK']['pnl_pct'] == 25.0 and pos['BOTTOK']['pnl_usd'] == 0.5
      and pos['BOTTOK']['stake_usd'] == 2.0 and pos['NARR']['pnl_pct'] == -20.0)
check('micro-cap prices keep their significant digits instead of rounding to six decimals',
      d._sig6(0.0000213987) == 0.0000213987 and d._sig6(0.00016016) == 0.00016016)
check('a held token no longer in the scanner still gets its real price, not the entry price',
      pos['GONE']['price_known'] and pos['GONE']['current_price'] == 0.012 and pos['GONE']['pnl_pct'] == 20.0)
with patch.object(d, 'get_token_data', return_value=None):
    blind = {p['token']: p for p in cl.get('/api/live-trades', base_url=B).get_json()['positions']}
check('...and a price that cannot be read shows as unknown, never a flat 0%',
      blind['GONE']['price_known'] is False and blind['GONE']['pnl_pct'] is None and blind['GONE']['pnl_usd'] == 0.0)

tr = api['trades']
check("bot trades are the bot's own finished round trips, newest first (no manual trades, no single legs)",
      [t['token'] for t in tr] == ['LOSS', 'WIN'])
win = tr[1]
check('...each with bought-at, sold-at and the result in dollars and percent',
      win['entry_price'] == 0.001 and win['exit_price'] == 0.0015
      and win['pnl_usd'] == 5.0 and win['pnl_pct'] == 50.0 and win['stake_usd'] == 10.0)
check('...why it sold, in words, and how long it was held',
      win['exit_reason'] == 'Take profit' and tr[0]['exit_reason'] == 'Stop loss'
      and win['hold_seconds'] == 1800 and win['sold_ts'] and win['bought_ts'])

us = d.get_user_state(w); us['trading_ready'] = 42.5; us['trading_ready_currency'] = 'USDC'
st = cl.get('/api/bot/status', base_url=B).get_json()
check('"Ready" is the capital the bot trades with (USDC), not the SOL fee balance',
      st['trading_ready'] == 42.5 and st['trading_ready_currency'] == 'USDC')

with patch.object(d, 'get_token_data', side_effect=fake_token):
    html = cl.get('/live-trades', base_url=B).get_data(as_text=True)
check('the page renders from the same data the poll returns',
      'var _ltInitial = {positions:' in html and '"BOTTOK"' in html and '"WIN"' in html
      and "fetch('/api/live-trades'" in html and '_ltRender(_ltInitial);' in html)
check('...with an Open positions and a Bot trades section, in English',
      '<h2>Open positions</h2>' in html and '<h2>Bot trades</h2>' in html
      and 'Bought ' in html and 'Sold ' in html
      and not any(nl in html for nl in ('Instap', 'Open sinds', '1e deel')))
raise SystemExit(0 if all(checks) else 1)
