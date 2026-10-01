"""The auto bot buys more easily -- the safety checks stay.

Before any other check, a token had to have a DexScreener profile (logo,
website or socials: paid metadata most new tokens never buy) plus >=300
transactions and >=30 sells in 24h. Then the picked token needed >=$20K
liquidity and a pair at least 30 minutes old. Together that kept a user's
bot from buying almost anything.

Now: no profile needed, >=100 transactions and >=10 real sells (still no
honeypots, still no unknown data), >=$10K liquidity (a $1-$3 stake moves
such a pool by well under 1%) and pairs from 10 minutes old. Every safety
check on the pick itself is unchanged.
"""
import ast, os
ROOT = os.path.join(os.path.dirname(__file__), '..')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
mod = ast.parse(src)
fn = next(n for n in mod.body if isinstance(n, ast.FunctionDef) and n.name == '_bot_gainers_eligible')
ns = {'BOT_MIN_24H_TXNS': 100, 'BOT_MIN_24H_SELLS': 10}
exec(compile(ast.Module(body=[fn], type_ignores=[]), 'x', 'exec'), ns)
ok = ns['_bot_gainers_eligible']
check('a token without a DexScreener profile can be bought', ok({'txns24h': 150, 'txns24h_sells': 20, 'has_profile': False}))
check('...it still has to really trade: >=100 transactions and >=10 sells in 24h, unknown is no pass',
      'BOT_MIN_24H_TXNS = 100' in src and 'BOT_MIN_24H_SELLS = 10' in src
      and not ok({'txns24h': 99, 'txns24h_sells': 20}) and not ok({'txns24h': 150, 'txns24h_sells': 9})
      and not ok({'txns24h': None, 'txns24h_sells': 20}) and not ok({}))
check('liquidity from $10K and pairs from 10 minutes old',
      "'min_liquidity_usd':     10000," in src and "'min_pair_age_minutes':  10," in src)
check('...the LP-lock requirement is unchanged', "'min_lp_locked_pct':     50," in src)
pick = src[src.index('for _pick_try in range(min(len(_pool), ENTRY_PICKS_PER_SCAN)):'):src.index('# ── Pass 2 (EVM): same idea')]
check('every safety check on the picked token is still there',
      all(x in pick for x in ("_safety['mint_authority_active'] or _safety['freeze_authority_active']",
                              "_lp['lp_locked_pct'] < _ai_filters['min_lp_locked_pct']",
                              "_lp.get('holder_concentration_risk')",
                              "_impact['price_impact_pct'] > MAX_ENTRY_PRICE_IMPACT_PCT",
                              "_edge['decision'] != 'PROCEED'")))
raise SystemExit(0 if all(checks) else 1)
