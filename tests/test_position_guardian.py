"""Manual holdings stay tracked without exits; protected bot positions keep theirs."""
import os, sqlite3, sys, tempfile, threading, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

def user(sl=8, tp=15):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = sqlite3.connect(d.DB_FILE)
    c.execute("UPDATE users SET stop_loss=?, take_profit=?, encrypted_private_key='enc-sol', "
              "encrypted_private_key_bsc='enc-evm', tiered_tp_enabled=0 WHERE id=?", (sl, tp, uid))
    c.commit(); c.close()
    return w, uid

def row(uid, mint):
    c = sqlite3.connect(d.DB_FILE)
    r = c.execute('SELECT amount, buy_price, sl_pct, tp_pct, protect_off FROM open_positions '
                  'WHERE user_id=? AND mint_address=?', (uid, mint)).fetchone()
    c.close(); return r

# Manual trades stay tracked but never inherit automatic exits.
for request in ({}, {'protect':True,'sl_pct':5,'tp_pct':20}, {'protect':'no'}):
    check('old clients cannot enable manual exits',d._manual_protection(request)==(False,None,None))
w,uid=user();mint=str(Keypair().pubkey())
d._register_manual_buy(uid,w,mint,'MAN',10.0,1000.0,(True,4,30))
check('new manual position has no exits',row(uid,mint)[2:]==(None,None,1))
d._register_manual_buy(uid,w,mint,'MAN',30.0,1000.0,(True,None,None))
check('manual topup retains tracking and weighted entry',row(uid,mint)[0]==2000 and abs(row(uid,mint)[1]-.02)<1e-12 and row(uid,mint)[4]==1)
d._reduce_after_manual_sell(uid,w,mint,500,False)
check('partial manual sell updates holdings',row(uid,mint)[0]==1500)
d._reduce_after_manual_sell(uid,w,mint,1500,True)
check('full manual sell closes holdings',row(uid,mint) is None)
def bot_buy(uid,w,mint,symbol,spend,amount,protection):
    d._register_manual_buy(uid,w,mint,symbol,spend,amount,protection)
    pos=d.get_user_state(w)['positions'][mint]
    pos['source']='bot'
    d._apply_manual_protection(pos,w,pos['buy_price'],protection)
    d._upsert_open_position(uid,w,mint,pos,source='bot')
legacy=str(Keypair().pubkey())
bot_buy(uid,w,legacy,'LEG',10,1000,(True,5,20))
bot_entry=d.get_user_state(w)['positions'][legacy]['buy_price']
d._register_manual_buy(uid,w,legacy,'LEG',2,100,(False,None,None))
check('manual topup preserves bot-owned exits',d.get_user_state(w)['positions'][legacy]['protect'] is True)
pos=d.get_user_state(w)['positions'][legacy];pos['source']='manual'
d._upsert_open_position(uid,w,legacy,pos,source='manual')
restored={'positions':{}};d._hydrate_positions_from_db(w,restored)
check('legacy manual exits disabled on hydration',restored['positions'][legacy].get('protect') is False and restored['positions'][legacy].get('sl_pct') is None)

# ── 2. the guardian ─────────────────────────────────────────────────────────
sold = []
def fake_exit(user_id, us, wallet, mint, pos, price, symbol, amount, spend, reason, *a, **k):
    sold.append((wallet, mint, reason)); return True, price, amount
d._bot_execute_exit = fake_exit
gw, gu = user(sl=10, tp=20)
mint_sl, mint_ok, mint_off, mint_tp = (str(Keypair().pubkey()) for _ in range(4))
bot_buy(gu, gw, mint_sl, 'DROP', 10.0, 1000.0, (True, None, None))   # entry 0.01
bot_buy(gu, gw, mint_ok, 'FINE', 10.0, 1000.0, (True, None, None))
d._register_manual_buy(gu, gw, mint_off, 'OFF', 10.0, 1000.0, (False, None, None))
bot_buy(gu, gw, mint_tp, 'MOON', 10.0, 1000.0, (True, 5.0, 25.0))
prices = {mint_sl: 0.0089, mint_ok: 0.0099, mint_off: 0.001, mint_tp: 0.0126}
d._exit_fresh_prices = lambda mints: {m: prices[m] for m in mints if m in prices}
d._guardian_users_cache['at'] = 0
d._guardian_pass(); time.sleep(0.5)
got = {m: r for (_w, m, r) in sold if _w == gw}
check('with the bot OFF, a position that hits its stop loss is sold by the guardian',
      mint_sl in got and got[mint_sl].startswith('STOP LOSS'))
check('...one that hits its take profit too', mint_tp in got and got[mint_tp].startswith('TAKE PROFIT'))
check('...one inside its range is left alone', mint_ok not in got)
check('...and one whose protection the user switched off is never sold', mint_off not in got)
check('a guardian sale closes the tracked position', row(gu, mint_sl) is None)

sold.clear()
bw, bu = user(sl=10, tp=20)
mint_b = str(Keypair().pubkey())
bot_buy(bu, bw, mint_b, 'BOT', 10.0, 1000.0, (True, None, None))
prices[mint_b] = 0.005
stop = threading.Event()
t = threading.Thread(target=stop.wait, daemon=True); t.start()
us = d.get_user_state(bw); us['trader_running'] = True; us['trader_thread'] = t
d._guardian_users_cache['at'] = 0
d._guardian_pass(); time.sleep(0.3)
check('a user whose bot is running is left to the bot\'s own exit watcher', not any(m == mint_b for _w, m, _r in sold))
us['trader_running'] = True; stop.set(); t.join()
d._guardian_users_cache['at'] = 0
d._guardian_pass(); time.sleep(0.3)
check('...but a bot that says it runs while its thread has died does not leave the position unwatched',
      any(m == mint_b for _w, m, _r in sold))

# no price: the user is told
pushed = []
d._send_push_notification = lambda uid, title, body, url='/', *a, **k: pushed.append((uid, title))
nw, nu = user()
mint_np = str(Keypair().pubkey())
bot_buy(nu, nw, mint_np, 'DARK', 10.0, 1000.0, (True, None, None))
d._guardian_users_cache['at'] = 0
d._guardian_pass()
d.get_user_state(nw)['positions'][mint_np]['_no_price_since'] = time.time() - 60
d._guardian_pass()
check('a watched position with no live price is not silent: the user gets a push',
      any(u == nu and t.startswith('Stop loss paused') for u, t in pushed))

# ── the shared lock ─────────────────────────────────────────────────────────
src = read('dashboard.py')
ex = src[src.index('def _bot_execute_exit('):src.index('def _bot_execute_exit_locked(')]
check('bot, guardian and manual sells share one per-position lock (never sold twice)',
      'lock = _get_sell_lock(wallet, mint, chain)' in ex and 'lock.acquire(blocking=False)' in ex
      and "(us['positions'].get(mint) or {}).get('amount', 0) <= 0" in ex)
it = src[src.index('def api_instant_trade('):src.index('def api_instant_trade(') + 30000]
check('Live Market\'s buy reads the protection before the swap and tracks the position after it',
      it.index('protection = _manual_protection(data)') < it.index('ok, sig, err_msg, token_amount, sol_amount = _execute_user_swap_ex(')
      and '_register_manual_buy(uid, wallet, token_address, symbol, sol_recorded,' in it
      and '_reduce_after_manual_sell(uid, wallet, token_address, token_amount,' in it)
check('EVM buys by hand get the same protection', "_register_manual_buy(user_id, wallet, token_address, symbol, float(purchase)," in src
      and 'protection = _manual_protection(data)' in src[src.index('def _evm_buy_flow('):])
check('the guardian starts with the app (switchable off for tests only)',
      "threading.Thread(target=_position_guardian_loop, name='position-guardian', daemon=True).start()" in src)
js = read('static', 'live-market-pro.js'); html = read('templates', 'live_market_pro.html')
check('manual protection UI removed', 'id="pt-protect"' not in html and '_loadProtectionDefaults' not in js)
check('manual buy explicitly disables exits', 'body.protect = false;' in js)
check('legacy manual position never sold by guardian', not any(m == legacy for _,m,_ in sold))
raise SystemExit(0 if all(checks) else 1)
