"""A stop loss must never go quietly blind.

- After every restart (every deploy) open positions were restored WITHOUT
  their own stop loss / take profit: each fell back to the account-wide
  settings, losing a custom or learned tighter stop and the trailing state.
- The exit watcher's fallback price (the last DexScreener read) was reused
  forever: with the live feeds down, a crashing token kept its old, higher
  price and its stop loss never fired.
- With Jupiter and DexScreener both unreachable there was no third source,
  and a held token without a price was skipped silently, every second.
- A stop-loss sell that kept failing only repeated in the activity log.
"""
import os, sqlite3, sys, tempfile
from unittest.mock import patch
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

# ── 1. a restart keeps each position's own stop loss / take profit ─────────
wallet = str(Keypair().pubkey()); uid = d.get_or_create_user(wallet)
mint = str(Keypair().pubkey())
c = sqlite3.connect(d.DB_FILE)
c.execute('''INSERT INTO open_positions (user_id, mint_address, symbol, amount, buy_price, spend, opened_at,
             source, chain, base_currency, sl_pct, tp_pct, sl_price, tp_price, trailing_enabled, entry_score,
             highest_price, lowest_price) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
          (uid, mint, 'TEST', 1000.0, 0.01, 10.0, 1.0, 'bot', 'solana', 'USDC', 4.0, 12.0, 0.0096, 0.0112,
           1, 7.5, 0.0108, 0.0099))
c.commit(); c.close()
us = {'positions': {}}
d._hydrate_positions_from_db(wallet, us)
p = us['positions'].get(mint, {})
check('after a restart a position keeps its own stop loss and take profit (it fell back to the account settings)',
      p.get('sl_pct') == 4.0 and p.get('tp_pct') == 12.0 and p.get('sl_price') == 0.0096)
check('...and its trailing setting and the peak/trough it already reached',
      p.get('trailing_enabled') is True and p.get('highest_price') == 0.0108 and p.get('lowest_price') == 0.0099)
check('...and it still sells back into USDC', p.get('base') == 'USDC')
check('the exit check uses that per-position stop', d._pos_sl_frac(p, 0.08) == 0.04)

# ── 2. a third price source when Jupiter and DexScreener are both down ─────
class R:
    def __init__(self, code, body): self.status_code, self._b = code, body
    def json(self): return self._b
def fake_get(url, *a, **k):
    if 'geckoterminal' in url:
        return R(200, {'data': {'attributes': {'token_prices': {mint: '0.0123'}}}})
    raise d.requests.RequestException('down')
with patch.object(d.requests, 'get', side_effect=fake_get), patch.object(d, '_dex_get', return_value=None):
    got = d._exit_fetch_prices({mint: 'solana'})
check('with Jupiter and DexScreener down the stop loss still gets a live price (GeckoTerminal)',
      abs(got.get(mint, 0) - 0.0123) < 1e-12)

src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
xp = src[src.index('    def _exit_pass():'):src.index('    def _exit_watch():')]
check('an old fallback price is never used for a stop-loss decision (max 3 s old)',
      "_EXIT_TD_PRICE_MAX_AGE = 3.0" in src and "_exit_td_at[mint] = time.time()" in src
      and "(_td.get('price') if _td_fresh else 0)" in xp)
check('a held token without any price is no longer skipped silently: the user is told, once',
      "if time.time() - _np >= EXIT_NO_PRICE_ALERT_SEC and not pos.get('_no_price_alerted'):" in xp
      and "'Stop loss paused: '" in xp and 'stop loss active again' in xp)
executor = open(os.path.join(ROOT,'protection_exits.py'),encoding='utf-8').read()
check('a stop-loss sell that keeps failing reaches the user and remains queued',
      "current['_sell_fails'] == ctx.get('EXIT_SELL_FAIL_ALERT', 5)" in executor
      and "'Could not sell '" in executor and 'retry queued' in executor)
check('the exit watcher keeps checking independently four times per second', 'EXIT_CHECK_INTERVAL   = 0.25' in src)
raise SystemExit(0 if all(checks) else 1)
