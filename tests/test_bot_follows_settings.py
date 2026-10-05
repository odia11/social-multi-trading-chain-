"""The auto trading bot sells exactly at the user's own stop loss / take profit.

It used to sell at levels the user never chose:
- a momentum exit after three falling prices (sold at -4% under a 20% stop);
- a fixed 15% crash exit (a user may set a stop loss up to 30%), also on
  bot start;
- a rugpull exit on falling liquidity or 24h volume;
- self-learning lowered the take profit and tightened the stop loss of new
  bot positions.
And on bot start a position bought by hand with protection switched OFF was
force-sold when it was below the stop loss.

Now a position exits on: its stop loss (also measured on what a sale really
returns), its take profit, and -- only when the user switched Trailing Stop
on -- the staged take profit with a trailing remainder.
"""
import os, re, sqlite3, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
import bot_learning  # noqa: E402
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
loop = src[src.index('def user_trader_loop('):src.index('def _guardian_pass():')]
xp = loop[loop.index('    def _exit_pass():'):loop.index('    def _exit_watch():')]
startup = loop[loop.index('# ── Immediate stop-loss pass on startup'):loop.index('    def _exit_pass():')]

reasons = set(re.findall(r"exit_reason = '([A-Z][A-Z ]*[A-Z])", xp)) | set(re.findall(r"'(TAKE PROFIT \d)", xp))
check('the bot sells only on stop loss, take profit or the user\'s own trailing stop',
      reasons <= {'STOP LOSS', 'TAKE PROFIT', 'TRAILING STOP', 'TAKE PROFIT 1', 'TAKE PROFIT 2'}
      and {'STOP LOSS', 'TAKE PROFIT'} <= reasons)
check('no momentum exit (it sold at -4% under a 20% stop loss)',
      'MOMENTUM EXIT' not in xp and '_confirmed_downtrend' not in src and 'MOMENTUM_EXIT_MIN_DROP' not in src)
check('no fixed 15% crash exit, in the 1-second check or on bot start',
      not any(x in part for part in (xp, startup) for x in ('CRASH EXIT', 'crash_exit'))
      and 'CRASH_EXIT' not in src)
check('no rugpull exit on liquidity or volume -- pulled liquidity is caught by the user\'s own stop '
      'loss on what a sale really returns', "'RUGPULL " not in xp and '_liquidity_stop(pos, mint, price, _eff_sl)' in xp)
check('every exit compares against the position\'s own (user) stop loss and take profit',
      "_protection_stop_hit(price, pos['buy_price'], _eff_sl)" in xp and "_protection_profit_hit(price, pos['buy_price'], _eff_tp)" in xp
      and '_eff_sl = _pos_sl_frac(pos, stop_loss)' in xp and '_eff_tp = _pos_tp_frac(pos, take_profit)' in xp)
check('the staged take profit / trailing stop only runs when the user switched Trailing Stop on',
      "_trailing_on  = pos.get('trailing_enabled', tiered_tp_enabled)" in xp
      and 'if _trailing_on and not pos.get(\'tp1_hit\'):' in xp)
check('a position bought by hand with protection OFF is never sold by the bot -- also not on bot start',
      "if _pos.get('protect') is False or _pos.get('source') == 'manual':" in startup and "if pos.get('protect') is False or pos.get('source') == 'manual':" in xp)

# A new bot position takes the user's settings exactly, whatever was learned.
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('UPDATE users SET stop_loss=20, take_profit=50, tiered_tp_enabled=0 WHERE id=?', (uid,))
c.commit(); c.close()
snap = d._snapshot_entry_risk(w, 1.0, entry_score=7.0)
check('a new bot position gets exactly the user\'s stop loss 20% and take profit 50%',
      snap['sl_pct'] == 20.0 and snap['tp_pct'] == 50.0 and snap['sl_price'] == 0.8 and snap['tp_price'] == 1.5)
try:
    d._snapshot_entry_risk(w, 1.0, entry_score=7.0, tuning={'tp': 9.0, 'sl': 5.0})
    takes_tuning = True
except TypeError:
    takes_tuning = False
check('...learning cannot hand it other exits any more', not takes_tuning and 'tuning=_tune' not in src)
check('self-learning only learns entries (minimum score, tokens to avoid), never exits',
      bot_learning.KNOBS == ('score_floor', 'avoid') and not hasattr(bot_learning, 'tune_exits'))

gp = src[src.index('def _guardian_pass():'):src.index('def _position_guardian_loop():')]
check('the position guardian (bot off) uses the same stop loss / take profit and nothing else',
      "_protection_profit_hit(price, pos['buy_price'], _pos_tp_frac(pos, cfg['tp']))" in gp and "_protection_stop_hit(price, pos['buy_price'], _sl)" in gp
      and 'MOMENTUM' not in gp and 'CRASH' not in gp and 'RUGPULL' not in gp)
page = open(os.path.join(ROOT, 'templates', 'auto_trading_bot.html'), encoding='utf-8').read()
js = open(os.path.join(ROOT, 'static', 'dashboard.js'), encoding='utf-8').read()
check('the app says so: no promise of a crash / rugpull exit, learning never changes your exits',
      'crashes -15%' not in js and 'Every position sells exactly at your own take profit and stop loss' in js
      and 'It never changes your take profit or stop loss' in page and 'earlier exits' not in page)
raise SystemExit(0 if all(checks) else 1)
