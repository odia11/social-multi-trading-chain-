"""Stop loss and take profit are checked every second and sold at once.

The exit checks used to be the first step of the bot's main loop, so they
waited on everything else that loop does -- reading balances over RPC,
vetting and buying new tokens -- plus a 2 s sleep, and they stopped entirely
during an RPC outage or a daily-loss pause. Prices came from one DexScreener
request per token (2-5 s cache; when DexScreener is down: an 8 s wait and
minutes-old data).

Now each running bot has an exit watcher thread that:
- re-checks every open position once a second (EXIT_CHECK_INTERVAL = 1.0);
- prices them from a shared 1-second feed: ONE batched request per second
  for every mint any bot holds (Jupiter for Solana, DexScreener batch as
  fallback), never acting on a price older than 15 s;
- sells a hit stop loss / take profit immediately, even while the main loop
  is stuck on a slow RPC call;
- is the only place the bot sells, so a position is never sold twice.

This test runs the real user_trader_loop against a simulated market.
"""
import os, sqlite3, sys, tempfile, threading, time
from unittest.mock import patch
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ORCAGENT_POSITION_GUARDIAN':'0',
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='})
import app_entry  # noqa: E402
d = app_entry._dashboard
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

# ── the shared feed: one batch per second for every watched mint ──
calls = []
def fake_fetch(mints_by_chain):
    calls.append(sorted(mints_by_chain)); return {m: 1.0 for m in mints_by_chain}
with patch.object(d, '_exit_fetch_prices', side_effect=fake_fetch):
    d._exit_price_cache.clear(); d._exit_watched.clear()
    d._exit_fresh_prices({'MintA':'solana'})
    time.sleep(.1)
    a = d._exit_fresh_prices({'MintA': 'solana'})
    d._exit_fresh_prices({'MintB':'solana'})
    time.sleep(.1)
    b = d._exit_fresh_prices({'MintB': 'solana'})
    time.sleep(1.05)
    d._exit_fresh_prices({'MintA': 'solana'})
    time.sleep(.1)
check('the exit feed reads every watched mint in one batch once a second, shared by all bots',
      a == {'MintA': 1.0} and b == {'MintB': 1.0} and calls[-1] == ['MintA', 'MintB'])
with patch.object(d, '_exit_fetch_prices', return_value={}):
    d._exit_price_cache['Old'] = (time.time() - 20, 5.0); d._exit_watched['Old'] = ('solana', time.time() + 10)
    check('a price older than 15 s is never acted on', d._exit_fresh_prices({'Old': 'solana'}) == {})
src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
feed_src = open(os.path.join(ROOT, 'protection_exits.py'), encoding='utf-8').read()
check('Solana prices come from Jupiter in batches of 50, EVM/missing from DexScreener in batches of 30',
      "'/price/v3?ids='+','.join(chunk)" in feed_src and 'range(0,len(sol),50)' in feed_src
      and "'https://api.dexscreener.com/latest/dex/tokens/'+','.join(chunk)" in feed_src)

# ── the real trader loop, with the main loop stuck on a slow RPC ──
wallet = str(Keypair().pubkey()); uid = d.get_or_create_user(wallet)
c = sqlite3.connect(d.DB_FILE)
c.execute('UPDATE users SET encrypted_private_key=?, stop_loss=10, take_profit=20 WHERE id=?',
          (d.encrypt_private_key(str(Keypair()), wallet), uid))
c.commit(); c.close()
SL, TP = str(Keypair().pubkey()), str(Keypair().pubkey())
us = d.get_user_state(wallet)
for mint, sym in ((SL, 'SLTEST'), (TP, 'TPTEST')):
    us['positions'][mint] = {'amount': 100.0, 'buy_price': 1.0, 'spend': 100.0, 'chain': 'solana',
                             'symbol': sym, 'sl_pct': 10.0, 'tp_pct': 20.0, 'base':'USDC'}
market = {SL: 0.95, TP: 1.05}
sells, fetches = [], []
def fake_prices(mints_by_chain):
    fetches.append(time.time()); return {m: market[m] for m in mints_by_chain if m in market}
def fake_exit(user_id, us_, wallet_, mint, pos, price, label, amount, spend, reason, *a, **kw):
    sells.append((mint, reason, time.time())); fake_close(user_id,wallet_,mint); return True, price, amount
def fake_close(user_id, wallet_, mint, chain='solana'):
    us['positions'][mint] = {'amount': 0.0, 'buy_price': 0.0, 'spend': 0.0}
def stuck_rpc(*a, **kw):
    time.sleep(30); raise RuntimeError('Solana bot balances unavailable from verified RPC')

stop = threading.Event()
with patch.object(d, '_exit_fetch_prices', side_effect=fake_prices), \
     patch.object(d, 'get_token_data', return_value=None), \
     patch.object(d, '_get_bot_solana_balances', side_effect=stuck_rpc), \
     patch.object(d, '_narrative_agent_cycle', return_value=None), \
     patch.object(d, '_bot_execute_exit', side_effect=fake_exit), \
     patch.object(d, '_close_open_position', side_effect=fake_close):
    d._exit_price_cache.clear(); d._exit_watched.clear()
    t = threading.Thread(target=d.user_trader_loop, args=(stop, {}, wallet), daemon=True)
    t.start(); started = time.time()
    time.sleep(2.5)
    check('inside the thresholds (-5% / +5%) nothing is sold', sells == [])
    market[SL] = 0.89; hit_sl = time.time()
    while not sells and time.time() - hit_sl < 5: time.sleep(0.05)
    sl_delay = (sells[0][2] - hit_sl) if sells else 99
    check('a hit stop loss (-11%% vs -10%%) is sold within ~1 s (%.2f s) while the main loop is stuck on RPC' % sl_delay,
          sells and sells[0][0] == SL and sells[0][1].startswith('STOP LOSS') and sl_delay <= 1.6)
    market[TP] = 1.25; hit_tp = time.time()
    while len(sells) < 2 and time.time() - hit_tp < 5: time.sleep(0.05)
    tp_delay = (sells[1][2] - hit_tp) if len(sells) > 1 else 99
    check('a hit take profit (+25%% vs +20%%) is sold within ~1 s (%.2f s)' % tp_delay,
          len(sells) > 1 and sells[1][0] == TP and sells[1][1].startswith('TAKE PROFIT') and tp_delay <= 1.6)
    time.sleep(2.5)
    check('each position is sold exactly once', [s[0] for s in sells] == [SL, TP])
    elapsed = time.time() - started
    stop.set()
check('prices were read about once a second (%d reads in %.1f s)' % (len(fetches), elapsed),
      elapsed - 3 <= len(fetches) <= elapsed + 2)
bot = open(os.path.join(ROOT, 'templates', 'auto_trading_bot.html'), encoding='utf-8').read()
check('the Bot page says so', '<span>Stop Loss / Take Profit</span><strong>Checked every second' in bot)
raise SystemExit(0 if all(checks) else 1)
