"""The auto trading bot never buys a token under a $50K market cap, whatever
the stake. The floor used to be tiered: $15K under a $5 stake, $50K up to
$50 and $100K above -- so the usual $1-$3 bot stakes could buy tokens worth
$15K. A losing streak still doubles the floor (it never lowers it).
"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

floors = {stake: d._min_marketcap_for_stake(stake) for stake in (0.5, 1, 3, 4.99, 5, 25, 49.99, 50, 100, 1000)}
check('the market-cap floor is $50K for every stake (was $15K under $5, $100K from $50)',
      set(floors.values()) == {50_000})
check('...also the fallback constant', d.MIN_MARKETCAP_USD == 50_000)
src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
loop = src[src.index('def user_trader_loop('):src.index('def _guardian_pass():')]
check('the bot applies it to every Solana entry, and a losing streak can only raise it',
      '_min_mcap = _min_marketcap_for_stake(min_trade_usdc)' in loop and '_min_mcap *= LOSS_STREAK_MCAP_MULT' in loop
      and 'if _mcap < _min_mcap:' in loop and d.LOSS_STREAK_MCAP_MULT >= 1)
raise SystemExit(0 if all(checks) else 1)
