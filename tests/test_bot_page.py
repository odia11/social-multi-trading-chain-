"""The menu's "Bot" opens the bot, not a marketing intro.

/bot used to show "Smarter Trading. Stronger Together." with four icons that
did nothing and a Start Trading button leading to a second page. Now /bot
(and /auto-trading-bot) is the bot itself:
- on/off, then what it is doing -- capital, win rate, trade count, what it
  holds now (entry and live result) and its last trades (bought -> sold, why,
  result) with a link to Live Trades -- then its settings;
- results in dollars (a USDC trade's pnl was shown as "SOL");
- stats count the bot's own finished round trips (scanner + Narrative
  agent), the same set Live Trades lists;
- pull-to-refresh and the 20s poll refresh all of it.
"""
import os, sqlite3, sys, tempfile, time, subprocess
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
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
c.execute('UPDATE users SET encrypted_private_key=? WHERE id=?', (d.encrypt_private_key(str(Keypair()), w), uid))
for tok, pnl, src, side in (('WIN', 5.0, 'bot', None), ('NARR', -1.0, 'narrative', None),
                            ('HAND', 9.0, 'manual', None), ('LEG', 50.0, 'bot', 'buy')):
    c.execute("INSERT INTO trades (user_id, token, entry_price, exit_price, amount, pnl, source, side, chain, base_currency) "
              "VALUES (?,?,1,1.5,10,?,?,?,'solana','USDC')", (uid, tok, pnl, src, side))
c.commit(); c.close()

cl = app.test_client(); B = 'https://orcagent.fun'
with cl.session_transaction(base_url=B) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = 'x' * 40
pages = {path: cl.get(path, base_url=B).get_data(as_text=True) for path in ('/bot', '/auto-trading-bot')}
check('/bot is the bot itself: on/off switch and settings, no marketing intro',
      all('id="bot-toggle-btn"' in h and 'id="bot-save"' in h and 'Stronger Together' not in h
          and 'bot-start-landing' not in h for h in pages.values()))
check('...and the old intro page and its in-app hook are gone',
      not os.path.exists(os.path.join(ROOT, 'templates', 'bot.html'))
      and 'wireBotLanding' not in read('static', 'app-ux.js'))

with patch.object(d, '_get_bot_solana_balances', return_value=(0.05, 42.5)):
    ov = cl.get('/api/bot/overview', base_url=B).get_json()
check('the overview reports the trading capital in USDC next to the SOL for fees',
      ov['trading_wallet_usdc'] == 42.5 and ov['trading_wallet_sol'] == 0.05)
check("stats count the bot's own finished trades (scanner + Narrative), not manual trades or single legs",
      ov['total_trades'] == 2 and ov['wins'] == 1 and ov['win_rate'] == 50.0)
check('best and worst trade come in dollars',
      ov['best_trade']['token'] == 'WIN' and ov['best_trade']['pnl_usd'] == 5.0
      and ov['worst_trade']['token'] == 'NARR' and ov['worst_trade']['pnl_usd'] == -1.0)

h = pages['/bot']
T = read('templates', 'auto_trading_bot.html')  # page script as written
check('the page shows what the bot is doing: capital, win rate, trades, holding now, last trades',
      all(i in h for i in ('id="ba-capital"', 'id="ba-winrate"', 'id="ba-trades"', 'id="ba-open"', 'id="ba-closed"'))
      and '<h2>Holding now</h2>' in h and '<h2>Last trades</h2>' in h and 'href="/live-trades">All trades' in h)
check('...from the same data as Live Trades, with entry, exit, why it sold and the result',
      "fetch('/api/live-trades'" in T and "Bought at '+price(p.entry_price)" in T
      and "price(t.entry_price)+' → '+price(t.exit_price)+' · '+esc(t.exit_reason)" in T
      and 'usd(t.pnl_usd,true)' in T)
check('...token names escaped, a tap opens the token in Live Market',
      "<b>$'+esc(p.token)+'</b>" in T and "'/live-market?mint='+encodeURIComponent(t.mint_address)+'&profile=1'" in T)
check('results in dollars, never a USDC number labelled SOL',
      'usd(r.best_trade.pnl_usd,true)' in T and 'fmtSol' not in T and 'Trading Capital' in h)
check('pull-to-refresh and the poll refresh status and activity together',
      'initPullToRefresh({onRefresh:refreshAll})' in T
      and 'setInterval(function(){if(!document.hidden)refreshAll()},20000);' in T)
check('the activity card has its own styles',
      'body.oa-bot-page .bot-activity{' in read('static', 'approved-bot.css'))
js = T[T.index('<script>\nvar CSRF'):]; js = js[len('<script>'):js.index('</script>')].replace('{{ csrf_token|tojson }}', '""')
r = subprocess.run(['node', '-e', 'new Function(require("fs").readFileSync(0,"utf8"))'], input=js,
                   capture_output=True, text=True, timeout=20)
check('the page script parses', r.returncode == 0)
raise SystemExit(0 if all(checks) else 1)
