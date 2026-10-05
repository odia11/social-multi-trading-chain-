"""Stop loss on what a sale would really return + admin "positions at risk".

3. The market price can sit still while liquidity is pulled and a sale would
   return a fraction of it. Every Solana position now also gets a Jupiter
   sell quote for its exact size; a worsening of that sell value (beyond the
   normal exit cost measured at the first quote) below the stop loss sells
   it, once two consecutive quotes agree. Implausible quotes are ignored.
5. The admin dashboard lists every open position the platform cannot fully
   protect right now: no live price, an exit sell that keeps failing, a
   sale returning far less than normal, or nobody watching it.
"""
import os, sqlite3, sys, tempfile, time
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

# ── 3. the sell-value stop ──────────────────────────────────────────────────
quotes = []          # (usd_per_token, quoted_at) returned in turn
real_orig = d._exit_realizable_price
d._exit_realizable_price = lambda mint, amount: quotes.pop(0) if quotes else (None, 0.0)
pos = {'amount': 1000.0, 'buy_price': 0.010, 'chain': 'solana', 'base': 'USDC'}
quotes[:] = [(0.0097, 1.0)]       # a normal 3% exit cost at the start
hit, chg = d._liquidity_stop(pos, 'MINT', 0.0100, 0.02)
check('the normal cost of selling is the baseline: a tight 2% stop does not sell on ordinary price impact',
      not hit and abs(chg) < 1e-9 and pos['_impact_base'] == 0.97)
quotes[:] = [(0.0049, 2.0)]       # liquidity pulled: a sale now returns half, the market price has not moved
hit, chg = d._liquidity_stop(pos, 'MINT', 0.0100, 0.08)
check('a sale suddenly returning half, while the market price looks unchanged, is seen as a -49% sell value',
      not hit and chg < -0.45)
quotes[:] = [(0.0049, 2.0)]       # the SAME quote again is not a second confirmation
hit, _ = d._liquidity_stop(pos, 'MINT', 0.0100, 0.08)
check('...one quote is not enough (the same quote twice does not count twice)', not hit)
quotes[:] = [(0.0048, 3.0)]
hit, _ = d._liquidity_stop(pos, 'MINT', 0.0100, 0.08)
check('...a second, newer quote that agrees triggers the stop loss', hit)

pos2 = {'amount': 1000.0, 'buy_price': 0.010, 'chain': 'solana', 'base': 'USDC'}
quotes[:] = [(0.0000001, 1.0), (0.0000001, 2.0)]
h1, c1 = d._liquidity_stop(pos2, 'M2', 0.0100, 0.08)
h2, c2 = d._liquidity_stop(pos2, 'M2', 0.0100, 0.08)
check('an implausible quote (wrong decimals, a glitch) is ignored, never acted on', not h1 and not h2 and c1 is None)
check('EVM positions keep the market-price stop only', d._liquidity_stop(
    {'amount': 1, 'buy_price': 1, 'chain': 'base'}, 'X', 1.0, 0.05) == (False, None))
check('no quote -> the market-price stop applies', d._liquidity_stop(
    {'amount': 1, 'buy_price': 1, 'chain': 'solana', 'base': 'USDC'}, 'Y', 1.0, 0.05) == (False, None))
d._exit_realizable_price = real_orig

class R:
    def __init__(self, b): self._b = b
    def json(self): return self._b
d.requests.post = lambda *a, **k: (_ for _ in ()).throw(d.requests.RequestException('down'))
d._token_decimals_cache.clear()
check('unknown token decimals -> no quote at all (never a guessed default of 6)',
      d._token_decimals_strict('Unknown111') is None and d._jupiter_sell_quote_usdc('Unknown111', 5.0) is None)

src = read('dashboard.py')
xp = src[src.index('    def _exit_pass():'):src.index('    def _exit_watch():')]
check('the bot sells on the sell-value stop too',
      '_liq_hit, _liq_chg = _liquidity_stop(pos, mint, price, _eff_sl)' in xp and "on sell value '" in xp)
gp = src[src.index('def _guardian_pass():'):src.index('def _position_guardian_loop():')]
check('...and so does the position guardian', 'liq_hit, liq_chg = _liquidity_stop(pos, mint, price, _sl)' in gp)
check('sell quotes are fetched in the background, never blocking the 1-second check',
      '_realizable_pool.submit(refresh)' in src and 'EXIT_REALIZABLE_TTL = 5.0' in src)

# ── 5. admin: positions at risk ─────────────────────────────────────────────
admin = str(Keypair().pubkey()); d.get_or_create_user(admin); d.ADMIN_WALLET = admin
member = str(Keypair().pubkey()); d.get_or_create_user(member)
us = d.get_user_state(member)
now = time.time()
us['positions'].update({
    'NOPRICE': {'amount': 10, 'buy_price': 1.0, 'spend': 10, 'symbol': 'DARK', 'chain': 'solana',
                '_no_price_since': now - 60},
    'FAILING': {'amount': 10, 'buy_price': 1.0, 'spend': 10, 'symbol': 'STUCK', 'chain': 'solana', '_sell_fails': 7},
    'THIN':    {'amount': 10, 'buy_price': 1.0, 'spend': 10, 'symbol': 'THIN', 'chain': 'solana', '_sell_value_ratio': 0.4},
    'FINE':    {'amount': 10, 'buy_price': 1.0, 'spend': 10, 'symbol': 'OK', 'chain': 'solana', 'base': 'USDC'},
})
d._guardian_state.update(running=False, last_pass=0)
data = d._positions_at_risk(now)
kinds = {r['symbol']: {i['kind'] for i in r['issues']} for r in data['at_risk']}
check('no live price, a failing sell and pulled liquidity are listed', 'no_price' in kinds.get('DARK', set())
      and 'sell_failing' in kinds.get('STUCK', set()) and 'liquidity' in kinds.get('THIN', set()))
check('with the bot off and the guardian not running, every position shows as unwatched',
      all('unwatched' in k for k in kinds.values()) and 'OK' in kinds)
d._guardian_state.update(running=True, last_pass=now)
data = d._positions_at_risk(now)
syms = {r['symbol'] for r in data['at_risk']}
check('with the guardian running, a healthy position is not at risk', 'OK' not in syms and data['guardian_running'])
check('the worst problems come first', data['at_risk'][0]['level'] == 3)

c = app_entry.app.test_client()
with c.session_transaction(base_url='https://orcagent.fun') as s:
    s['wallet'] = member; s['csrf_token'] = 'x' * 30
check('only staff can see it', c.get('/api/admin/positions-at-risk', base_url='https://orcagent.fun').status_code in (401, 403))
with c.session_transaction(base_url='https://orcagent.fun') as s:
    s['wallet'] = admin; s['csrf_token'] = 'x' * 30
r = c.get('/api/admin/positions-at-risk', base_url='https://orcagent.fun')
j = r.get_json() or {}
check('the admin sees the list with counts', r.status_code == 200 and j.get('count', 0) >= 3 and 'watched' in j)
page = c.get('/admin', base_url='https://orcagent.fun')
check('the admin page still renders (a CSS "{#" once broke the template)', page.status_code == 200
      and b'id="view-risk"' in page.data)
html = read('templates', 'admin.html')
check('the admin dashboard has a "Positions at risk" page with a red badge, escaping what it shows',
      'id="view-risk"' in html and 'data-badge="risk"' in html and "trading:  ['risk','performance','aifilters']" in html
      and '_riskEsc(r.symbol)' in html and '_riskEsc(i.text)' in html)
raise SystemExit(0 if all(checks) else 1)
