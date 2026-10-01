"""A running bot that cannot buy says why.

With less on Solana than the user's own minimum trade size (seen: $0.13 USDC
against a $1.00 minimum), every candidate fell through the
`spend <= balance` check without a word: the bot looked alive ("Scanning…")
and bought nothing for hours. It now writes the reason in the activity log
(every few minutes), sends one phone push (every few hours), and the bot
page shows it under "Running".
"""
import os, sys, tempfile
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

src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
loop = src[src.index('def user_trader_loop('):src.index('def _guardian_pass():')]
block = loop[loop.index('# ── Not enough to buy: say so instead of skipping quietly ──'):
             loop.index('# ── Pass 2: pick the single best entry ──')]
check('below the minimum trade size the bot names the reason, with both amounts',
      'us_solana_avail < _min_needed' in block and "f'{_fmt(us_solana_avail)} available, your minimum trade is '" in block
      and "_min_needed = (min_trade_usdc if _solana_base == 'USDC'" in block)
check('...in the activity log every few minutes and as one push every few hours',
      "add_user_log(wallet, '[' + short + '] ⚠ ' + us['buy_blocked'])" in block
      and "_send_push_notification(" in block and "tag='bot-low-balance'" in block
      and 'LOW_BALANCE_LOG_SEC = 300 ' in src and 'LOW_BALANCE_PUSH_SEC = 6 * 3600 ' in src)
check('...and clears it as soon as there is enough again', "us['buy_blocked'] = None" in block)
check('it runs before the entry scan, every round', loop.index('# ── Not enough to buy') < loop.index('# ── Pass 2: pick the single best entry ──'))

w = str(Keypair().pubkey()); d.get_or_create_user(w)
c = app_entry.app.test_client()
with c.session_transaction(base_url='https://orcagent.fun') as s:
    s['wallet'] = w; s['csrf_token'] = 'x' * 30
us = d.get_user_state(w)
us['buy_blocked'] = 'Not enough USDC on Solana to buy: $0.13 available, your minimum trade is $1.00. Deposit USDC to let the bot trade.'
us['trader_running'] = False
r = c.get('/api/bot/overview', base_url='https://orcagent.fun').get_json() or {}
check('a stopped bot shows no buy warning', r.get('ok') and r.get('buy_blocked') is None)
us['trader_running'] = True
r = c.get('/api/bot/overview', base_url='https://orcagent.fun').get_json() or {}
check('a running bot that cannot buy reports why to the bot page', (r.get('buy_blocked') or '').startswith('Not enough USDC'))
page = open(os.path.join(ROOT, 'templates', 'auto_trading_bot.html'), encoding='utf-8').read()
check('the bot page shows it under "Running", highlighted', 'if(running&&r.buy_blocked)sub.textContent=r.buy_blocked;' in page
      and '.bot-warn{' in page)
us['trader_running'] = False
raise SystemExit(0 if all(checks) else 1)
