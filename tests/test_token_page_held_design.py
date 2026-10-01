"""The Live Market token page of a token you hold, built as the "Held" design.

- "Your position" says when you bought ("You bought 2h ago"): the holding
  answer now carries the position's opened_at.
- The chart draws a dashed "You bought at $…" line at your entry price.
- Market data: Market cap first, plain tiles, "Buys / sells 24h" as a
  green/red bar with both counts.
- "On OrcAgent": how many friends hold it, then the latest BUY / SELL by you
  and the people you follow, in dollars, newest first
  (/api/token/<mint>/activity).
- About is titled "About $SYMBOL".
"""
import datetime, os, sqlite3, sys, tempfile, time
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

BASE = 'https://orcagent.fun'
def person(name):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = sqlite3.connect(d.DB_FILE); c.execute('UPDATE users SET username=? WHERE id=?', (name, uid)); c.commit(); c.close()
    return w, uid

me_w, me = person('coinprotocol')
maria_w, maria = person('maria')
deni_w, deni = person('deni3d')
stranger_w, stranger = person('stranger')
mint = str(Keypair().pubkey())
now = time.time()
iso = lambda t: datetime.datetime.utcfromtimestamp(t).strftime('%Y-%m-%dT%H:%M:%SZ')
c = sqlite3.connect(d.DB_FILE)
c.executemany('INSERT INTO follows (follower_id, following_id) VALUES (?,?)', [(me, maria), (me, deni)])
pos_sql = ('INSERT INTO open_positions (user_id, mint_address, symbol, amount, buy_price, spend, opened_at, '
           'source, chain, base_currency) VALUES (?,?,?,?,?,?,?,?,?,?)')
# maria's bot bought $25 two minutes ago and still holds it
c.execute(pos_sql, (maria, mint, 'POPCAT', 120000, 0.000208, 25.0, now - 120, 'bot', 'solana', 'USDC'))
# my own buy by hand: a side='buy' row AND (protected) an open position -- one BUY, not two
c.execute(pos_sql, (me, mint, 'POPCAT', 54000, 0.000182, 9.83, now - 3600, 'manual', 'solana', 'USDC'))
tr_sql = ('INSERT INTO trades (user_id, token, entry_price, exit_price, amount, pnl, timestamp, opened_at, '
          'mint_address, source, side, chain, base_currency) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)')
c.execute(tr_sql, (me, 'POPCAT', 0, 0, 9.83, 0, iso(now - 3600), None, mint, 'manual', 'buy', 'solana', 'USDC'))
# deni3d's bot sold 64,000 at 0.00021 fifteen minutes ago, bought them 3h ago at 0.0002
c.execute(tr_sql, (deni, 'POPCAT', 0.0002, 0.00021, 64000, 0.64, iso(now - 900), now - 10800, mint, 'bot', None, 'solana', 'USDC'))
# someone I do not follow, and an old trade of a friend: not on my list
c.execute(tr_sql, (stranger, 'POPCAT', 0, 0, 500, 0, iso(now - 60), None, mint, 'manual', 'buy', 'solana', 'USDC'))
c.execute(tr_sql, (maria, 'POPCAT', 0, 0, 77, 0, iso(now - 40 * 86400), None, mint, 'manual', 'buy', 'solana', 'USDC'))
c.commit(); c.close()

client = app_entry.app.test_client()
check('the activity list needs a login', client.get(f'/api/token/{mint}/activity', base_url=BASE).status_code == 401)
with client.session_transaction(base_url=BASE) as s:
    s['wallet'] = me_w; s['user_id'] = me; s['csrf_token'] = 'x' * 30
r = client.get(f'/api/token/{mint}/activity', base_url=BASE)
ev = (r.get_json() or {}).get('events') or []
got = [(e['side'], e['username'], e['usd'], bool(e['you'])) for e in ev]
check('On OrcAgent lists the latest buys and sells by me and the people I follow, newest first',
      r.status_code == 200 and got == [('buy', 'maria', 25.0, False), ('sell', 'deni3d', 13.44, False),
                                       ('buy', 'coinprotocol', 9.83, True), ('buy', 'deni3d', 12.8, False)])
check('...my buy by hand is listed once (not again for its protected position)',
      sum(1 for e in ev if e['you']) == 1)
check('...nobody I do not follow, and nothing older than the window',
      all(e['username'] != 'stranger' for e in ev) and all(e['usd'] != 77 for e in ev))
check('a bad mint is refused', client.get('/api/token/not-a-mint/activity', base_url=BASE).status_code == 400)

us = d.get_user_state(me_w)
us['positions'][mint] = {'amount': 54000.0, 'buy_price': 0.000182, 'spend': 9.83, 'symbol': 'POPCAT',
                         'base_currency': 'USDC', 'opened_at': now - 7200, 'chain': 'solana'}
d.get_token_data = lambda *a, **k: {'price': 0.000207}
h = client.get(f'/api/trade/holding?chain=solana&token_address={mint}', base_url=BASE).get_json() or {}
check('the holding answer says when the position was opened ("You bought 2h ago")',
      h.get('ok') and abs((h.get('opened_at') or 0) - (now - 7200)) < 1 and h.get('cost_usd') == 9.83)

js = read('static', 'live-market-pro.js'); html = read('templates', 'live_market_pro.html')
check('Your position shows when you bought', "'You bought ' + fmtAge(Number(h.opened_at) * 1000) + ' ago'" in js)
check('the chart draws "You bought at" at the entry price on the page of a token you hold',
      "esc('You bought at '+fmtPrice(entryPx))" in js and 'var entryPx = _pfEntryPrice(idx);' in js
      and 'if(held && st && st.candles) renderChartSvg(idx, st.candles, _cardRefPrice(st, idx));' in js)
check('market data as on the design: Market cap first, Buys / sells 24h as a bar with both counts',
      'liq.parentNode.insertBefore(mcap, liq)' in js and "'Buys / sells 24h'" in js and '.pt-pf-ratio-bar' in html
      and 'body.pt-profile-mode .pt-card.pt-profile-open .pt-stat-row:before{display:none!important}' in html)
check('...and closing the page puts the feed card back as it was',
      'liq.parentNode.insertBefore(liq, mcap)' in js and "lbl.textContent = 'Buy / Sell'" in js)
check('On OrcAgent: friends who hold it and the BUY / SELL list, built as text (no HTML injection)',
      "_pfNode('h3', 'pt-pf-h', 'On OrcAgent')" in js and "fetch('/api/token/' + encodeURIComponent(mint) + '/activity'" in js
      and "e.you ? 'You' : '@' + (e.username || 'trader')" in js and '.pt-pf-act-side.buy' in html)
check('...On OrcAgent comes before Safety checks, as on the design',
      js.index("_pfSection(card, 'pt-pf-community');") < js.index("_pfSection(card, 'pt-pf-safety').hidden = true;")
      and '.pt-pf-community{order:7' in html and '.pt-pf-safety{order:8}' in html)
check('About is titled with the token symbol', "title.textContent=_sym?'About $'+_sym" in js)
raise SystemExit(0 if all(checks) else 1)
