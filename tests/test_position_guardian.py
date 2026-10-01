"""Every position has a stop loss that is actually watched.

1. A buy made by hand in Live Market used to create no tracked position at
   all, so it had no stop loss / take profit. It is now tracked, protected
   by default at the user's own settings; the buy sheet can change the
   values or switch protection off. A sell by hand keeps the position in
   step (and never tells copiers twice).
2. Stop loss / take profit used to be watched only inside a running bot. A
   position held while the bot is off is now watched every second by the
   position guardian. The bot, the guardian and a manual sell share one
   per-position lock, so the same tokens are never sold twice.
"""
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

# ── 1. protection for buys by hand ──────────────────────────────────────────
check('a buy by hand is protected by default, at the user\'s own settings',
      d._manual_protection({}) == (True, None, None))
check('...the buy sheet can set other values', d._manual_protection({'sl_pct': 5, 'tp_pct': 20}) == (True, 5.0, 20.0))
check('...or switch it off', d._manual_protection({'protect': False}) == (False, None, None))
for bad in ({'sl_pct': 50, 'tp_pct': 60}, {'sl_pct': 10, 'tp_pct': 5}, {'protect': 'no'}):
    try:
        d._manual_protection(bad); ok = False
    except ValueError:
        ok = True
    check(f'...and values the app refuses in Settings are refused here too ({bad})', ok)

w, uid = user(sl=8, tp=15)
mint = str(Keypair().pubkey())
d._register_manual_buy(uid, w, mint, 'MAN', 10.0, 1000.0, (True, None, None))
r = row(uid, mint)
check('the Live Market buy becomes a tracked position with the user\'s stop loss / take profit',
      r and abs(r[1] - 0.01) < 1e-12 and r[2] == 8.0 and r[3] == 15.0 and r[4] == 0)
d._register_manual_buy(uid, w, mint, 'MAN', 30.0, 1000.0, (True, None, None))
r = row(uid, mint)
check('buying more adds to it at the averaged entry, keeping its protection',
      abs(r[0] - 2000) < 1e-9 and abs(r[1] - 0.02) < 1e-12 and r[2] == 8.0)
copied = []
orig_copy_sell = d._trigger_copy_sell
d._trigger_copy_sell = lambda *a, **k: copied.append(a)
d._reduce_after_manual_sell(uid, w, mint, 500.0, False)
r = row(uid, mint)
check('a partial sell by hand shrinks the tracked position', abs(r[0] - 1500) < 1e-9)
d._reduce_after_manual_sell(uid, w, mint, 1500.0, True)
check('selling everything by hand closes it -- without telling copiers a second time',
      row(uid, mint) is None and not copied)
d._trigger_copy_sell = orig_copy_sell

m2, m3 = str(Keypair().pubkey()), str(Keypair().pubkey())
d._register_manual_buy(uid, w, m2, 'CUS', 10.0, 100.0, (True, 4.0, 30.0))
d._register_manual_buy(uid, w, m3, 'OFF', 10.0, 100.0, (False, None, None))
check('custom values are stored on the position', row(uid, m2)[2:4] == (4.0, 30.0))
check('"off" is stored too (no stop loss), and survives a restart',
      row(uid, m3)[4] == 1 and row(uid, m3)[2] is None)
us2 = {'positions': {}}
d._hydrate_positions_from_db(w, us2)
check('...restored as unprotected, so neither the bot nor the guardian sells it',
      us2['positions'][m3].get('protect') is False and us2['positions'][m2].get('sl_pct') == 4.0)

# ── 2. the guardian ─────────────────────────────────────────────────────────
sold = []
def fake_exit(user_id, us, wallet, mint, pos, price, symbol, amount, spend, reason, *a, **k):
    sold.append((wallet, mint, reason)); return True, price, amount
d._bot_execute_exit = fake_exit
gw, gu = user(sl=10, tp=20)
mint_sl, mint_ok, mint_off, mint_tp = (str(Keypair().pubkey()) for _ in range(4))
d._register_manual_buy(gu, gw, mint_sl, 'DROP', 10.0, 1000.0, (True, None, None))   # entry 0.01
d._register_manual_buy(gu, gw, mint_ok, 'FINE', 10.0, 1000.0, (True, None, None))
d._register_manual_buy(gu, gw, mint_off, 'OFF', 10.0, 1000.0, (False, None, None))
d._register_manual_buy(gu, gw, mint_tp, 'MOON', 10.0, 1000.0, (True, 5.0, 25.0))
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
d._register_manual_buy(bu, bw, mint_b, 'BOT', 10.0, 1000.0, (True, None, None))
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
d._register_manual_buy(nu, nw, mint_np, 'DARK', 10.0, 1000.0, (True, None, None))
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
      and '_register_manual_buy(uid, wallet, token_address, symbol, amount_sol,' in it
      and '_reduce_after_manual_sell(uid, wallet, token_address, token_amount,' in it)
check('EVM buys by hand get the same protection', "_register_manual_buy(user_id, wallet, token_address, symbol, float(purchase)," in src
      and 'protection = _manual_protection(data)' in src[src.index('def _evm_buy_flow('):])
check('the guardian starts with the app (switchable off for tests only)',
      "threading.Thread(target=_position_guardian_loop, name='position-guardian', daemon=True).start()" in src)
js = read('static', 'live-market-pro.js'); html = read('templates', 'live_market_pro.html')
check('the buy sheet shows the protection, starting at the user\'s settings, editable or off',
      'id="pt-protect"' in html and 'id="pt-protect-on"' in html and 'id="pt-protect-sl"' in html
      and "fetch('/api/bot/overview'" in js and '_loadProtectionDefaults();' in js)
check('...and every buy sends it', 'body.protect = prot.protect;' in js and 'body.sl_pct = prot.sl; body.tp_pct = prot.tp;' in js)
raise SystemExit(0 if all(checks) else 1)
