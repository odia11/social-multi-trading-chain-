"""Self-learning auto trading bot (bot_learning.py).

The bot replays each user's own closed bot trades and applies what the
evidence supports, with no approval needed: tighter exits that would have
done better, a higher minimum entry score, kinds of entries to avoid. It
must not learn from noise, must never loosen the user's own risk settings,
must roll a change back when the next trades do worse, and must stop
entirely when the user switches it off.
"""
import os, random, sqlite3, sys, tempfile, time
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
import bot_learning as bl  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

SCHEMA = '''CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, token TEXT,
    mint_address TEXT, opened_at REAL, entry_price REAL, exit_price REAL, amount REAL, exit_reason TEXT,
    sl_pct REAL, tp_pct REAL, highest_price REAL, lowest_price REAL, entry_score REAL,
    entry_pair_age_minutes REAL, entry_market_cap REAL, entry_buy_sell_ratio REAL,
    chain TEXT DEFAULT 'solana', source TEXT DEFAULT 'bot')'''


def db():
    path = os.path.join(tempfile.mkdtemp(prefix='bot-learning-'), 'x.db')
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return path, conn


n = [0]
def trade(conn, pnl, peak, trough, reason, sl=10.0, tp=20.0, score=7.0, age=120.0, mcap=1e6,
          bsr=1.5, chain='solana', user=1, source='bot'):
    n[0] += 1
    e = 1.0
    conn.execute('''INSERT INTO trades (user_id, token, mint_address, opened_at, entry_price, exit_price,
        amount, exit_reason, sl_pct, tp_pct, highest_price, lowest_price, entry_score,
        entry_pair_age_minutes, entry_market_cap, entry_buy_sell_ratio, chain, source)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                 (user, 'T%d' % n[0], 'M%d' % n[0], 1000.0 + n[0], e, e * (1 + pnl / 100), 100.0, reason,
                  sl, tp, e * (1 + peak / 100), e * (1 - trough / 100), score, age, mcap, bsr, chain, source))


# ── 1. too little evidence: nothing changes ────────────────────────────────
path, conn = db()
for _ in range(10):
    trade(conn, -10.6, 9.0, 10.0, 'STOP LOSS -10.6%')
conn.commit()
t = bl.tuning_for(path, 1, 20.0, 10.0, force=True)
check('under 20 closed bot trades nothing is learned', t == {'tp': None, 'sl': None, 'score_floor': None, 'avoid': []})

# ── 2. trades keep peaking ~+9% then dying at the stop: a lower TP is learned ─
path, conn = db()
for i in range(30):
    if i % 3 == 0:
        trade(conn, 20.5, 21.0, 2.0, 'TAKE PROFIT +20.5%')
    else:
        trade(conn, -5.6, 9.0 + (i % 2), 5.0, 'STOP LOSS -5.6%', sl=5.0)
conn.commit()
t = bl.tuning_for(path, 1, 20.0, 5.0, force=True)
check('a lower take profit is learned when trades kept giving back a ~9% peak',
      t['tp'] is not None and 4.0 <= t['tp'] <= 9.0)
check('learned exits are never wider than the user\'s own settings, and TP stays above SL',
      (t['tp'] or 0) <= 20.0 and (t['sl'] is None or t['sl'] <= 5.0)
      and (t['tp'] is None or t['sl'] is None or t['tp'] > t['sl']))
st = sqlite3.connect(path).execute('SELECT state FROM bot_learning WHERE user_id=1').fetchone()[0]
log = [m for (m,) in sqlite3.connect(path).execute('SELECT message FROM bot_learning_log')]
check('the change is logged in plain words and put under measurement',
      any('Learned from your last 30 bot trades' in m and 'take profit' in m for m in log) and '"pending"' in st)

# replayed result really is better on these trades (sanity of the replay)
pos = bl.load_positions(sqlite3.connect(path), 1)
costs = bl._exec_costs(pos)
check('replay: the learned exits beat what really happened on these trades',
      sum(bl.replay(p, t['tp'], t['sl'], costs) for p in pos) > sum(p['pnl'] for p in pos))
check('replay never invents a wider exit (TP above the trade\'s own target changes nothing)',
      all(bl.replay(p, 50.0, None, costs) == p['pnl'] for p in pos))

# ── 3. noise: random trades, no edge in any change -> nothing applied ──────
path, conn = db()
rng = random.Random(7)
for i in range(60):
    if rng.random() < 0.5:
        trade(conn, 20.4, 20.5 + rng.random(), rng.uniform(0, 9.5), 'TAKE PROFIT +20.4%',
              score=rng.uniform(5, 9), age=rng.uniform(1, 2000), mcap=rng.uniform(5e4, 2e7), bsr=rng.uniform(0.5, 3))
    else:
        trade(conn, -10.3, rng.uniform(0, 3), 10.3, 'STOP LOSS -10.3%',
              score=rng.uniform(5, 9), age=rng.uniform(1, 2000), mcap=rng.uniform(5e4, 2e7), bsr=rng.uniform(0.5, 3))
conn.commit()
t = bl.tuning_for(path, 1, 20.0, 10.0, force=True)
check('random trades with no pattern teach the bot nothing', t == {'tp': None, 'sl': None, 'score_floor': None, 'avoid': []})

# 60 more random histories: an entry rule learned from pure noise must be rare
fp = 0
for seed in range(60):
    path, conn = db()
    rng = random.Random(1000 + seed)
    for i in range(80):
        kw = dict(score=rng.uniform(5, 9), age=rng.uniform(1, 3000), mcap=rng.uniform(5e4, 2e7), bsr=rng.uniform(.4, 3))
        if rng.random() < 0.45:
            trade(conn, 20.3, rng.uniform(20, 40), rng.uniform(0, 9.9), 'TAKE PROFIT', **kw)
        else:
            trade(conn, -10.4, rng.uniform(0, 19), 10.4, 'STOP LOSS', **kw)
    conn.commit()
    a = bl.analyse(bl.load_positions(conn, 1), 20.0, 10.0)
    fp += bool(a['score_floor'] or a['avoid'])
check(f'entry rules learned from pure noise stay rare ({fp}/60 random histories, max 2)', fp <= 2)

# ── 4. low entry scores lose: the minimum score goes up ────────────────────
path, conn = db()
for i in range(40):
    if i % 2:
        trade(conn, -8.0, 1.0, 8.0, 'MOMENTUM EXIT -8.0%', score=5.5 + (i % 4) * 0.1)
    else:
        trade(conn, 12.0, 13.0, 2.0, 'MOMENTUM EXIT 12.0%', score=7.5)
conn.commit()
t = bl.tuning_for(path, 1, 20.0, 10.0, force=True)
check('a higher minimum entry score is learned when low-score entries lost',
      t['score_floor'] is not None and 6.0 <= t['score_floor'] <= 7.5)

# ── 5. brand-new tokens keep losing: they are avoided, others are not ──────
path, conn = db()
for i in range(40):
    if i % 3 == 0:
        trade(conn, -9.0, 1.0, 9.0, 'MOMENTUM EXIT -9.0%', age=5.0)
    else:
        trade(conn, 6.0, 7.0, 2.0, 'MOMENTUM EXIT 6.0%', age=300.0)
conn.commit()
t = bl.tuning_for(path, 1, 20.0, 10.0, force=True)
check('entries in a losing bucket (tokens under 15 min old) are avoided',
      [a['label'] for a in t['avoid']] == ['under 15 min old'])
young = {'pairCreatedAt': (time.time() - 5 * 60) * 1000, 'market_cap': 1e6, 'txns_buys': 3, 'txns_sells': 2}
older = dict(young, pairCreatedAt=(time.time() - 300 * 60) * 1000)
check('the live candidate check matches the learned rule (young skipped, older kept)',
      bl.avoid_reason(t, 'solana', **bl.candidate_features(young)) == 'under 15 min old'
      and bl.avoid_reason(t, 'solana', **bl.candidate_features(older)) == '')
check('Solana itself is never "avoided" (that would stop the bot)',
      all(a['dim'] != 'chain' or a['label'] != 'solana' for a in t['avoid']))

# ── 6. measurement: worse next trades roll the change back ─────────────────
path, conn = db()
for i in range(30):
    if i % 3 == 0:
        trade(conn, 20.5, 21.0, 2.0, 'TAKE PROFIT +20.5%', sl=5.0)
    else:
        trade(conn, -5.6, 9.0, 5.0, 'STOP LOSS -5.6%', sl=5.0)
conn.commit()
first = bl.tuning_for(path, 1, 20.0, 5.0, force=True)
for i in range(15):
    trade(conn, -15.0, 1.0, 15.0, 'STOP LOSS -15.0%', tp=first['tp'] or 20.0, sl=5.0)
conn.commit()
after = bl.tuning_for(path, 1, 20.0, 5.0, force=True)
log = [m for (m,) in sqlite3.connect(path).execute('SELECT message FROM bot_learning_log ORDER BY id')]
check('a change whose next 15 trades did worse is rolled back automatically',
      first['tp'] is not None and after['tp'] is None and any(m.startswith('Rolled back') for m in log))
again = bl.tuning_for(path, 1, 20.0, 5.0, force=True)
check('...and that knob then rests instead of flipping straight back', again['tp'] is None)

# ── 7. measurement: better next trades keep it ─────────────────────────────
path, conn = db()
for i in range(30):
    if i % 3 == 0:
        trade(conn, 20.5, 21.0, 2.0, 'TAKE PROFIT +20.5%', sl=5.0)
    else:
        trade(conn, -5.6, 9.0, 5.0, 'STOP LOSS -5.6%', sl=5.0)
conn.commit()
first = bl.tuning_for(path, 1, 20.0, 5.0, force=True)
for i in range(15):
    trade(conn, first['tp'] - 0.5, first['tp'] + 1, 1.0, 'TAKE PROFIT', tp=first['tp'], sl=5.0)
conn.commit()
kept = bl.tuning_for(path, 1, 20.0, 5.0, force=True)
log = [m for (m,) in sqlite3.connect(path).execute('SELECT message FROM bot_learning_log ORDER BY id')]
check('a change whose next 15 trades did better is kept', kept['tp'] == first['tp'] and any(m.startswith('Kept') for m in log))
lower = bl.tuning_for(path, 1, first['tp'] - 1.0, 2.0, force=True)
check('a user whose own take profit is already lower than the learned one keeps their own',
      lower['tp'] is None)

# ── 8. switched off: the bot uses the user's own settings only ─────────────
c = sqlite3.connect(path)
c.execute('UPDATE bot_learning SET enabled=0 WHERE user_id=1'); c.commit()
check('switched off, nothing learned is applied', bl.tuning_for(path, 1, 20.0, 5.0, force=True)
      == {'tp': None, 'sl': None, 'score_floor': None, 'avoid': []})

# ── 9. only the user's own BOT trades count ────────────────────────────────
path, conn = db()
for i in range(30):
    trade(conn, -10.6, 9.0, 10.0, 'MANUAL SELL', source='manual')
    trade(conn, -10.6, 9.0, 10.0, 'STOP LOSS -10.6%', user=2)
conn.commit()
check('manual trades and other users\' trades are not learned from',
      bl.tuning_for(path, 1, 20.0, 10.0, force=True) == {'tp': None, 'sl': None, 'score_floor': None, 'avoid': []})

# ── 10. wiring in the live bot ─────────────────────────────────────────────
src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
entry = open(os.path.join(ROOT, 'app_entry.py'), encoding='utf-8').read()
check('the bot loop reads the learned tuning for every entry scan',
      "_tune = bot_learning.tuning_for(DB_FILE, user_id, take_profit * 100, stop_loss * 100)" in src)
check('learned minimum score and avoided entries gate the Solana entry',
      "_score_floor = _tune['score_floor']" in src
      and "bot_learning.avoid_reason(\n                            _tune, 'solana', **bot_learning.candidate_features(_t))" in src)
check('a bot buy snapshots the learned (tighter) exits; manual/copy buys do not',
      src.count('tuning=_tune))') == 1 and "if tuning.get('sl') and tuning['sl'] < sl_pct:" in src
      and "tuning['tp'] < tp_pct and not trailing_enabled" in src)
check('a learned losing chain is skipped by the EVM entry scan', 'continue  # learned: this user' in src)
check('every closed trade triggers a fresh analysis', 'bot_learning.invalidate(user_id)' in src)
check('the bot page API is installed', '_install_bot_learning(_dashboard)' in entry)
# ── 11. the bot page API ───────────────────────────────────────────────────
from types import SimpleNamespace
from flask import Flask, session
path, conn = db()
conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, wallet_address TEXT, take_profit REAL, stop_loss REAL)')
conn.execute("INSERT INTO users VALUES (1, 'W1', 20.0, 5.0)")
for i in range(30):
    if i % 3 == 0:
        trade(conn, 20.5, 21.0, 2.0, 'TAKE PROFIT +20.5%', sl=5.0)
    else:
        trade(conn, -5.6, 9.0, 5.0, 'STOP LOSS -5.6%', sl=5.0)
conn.commit()
bl.tuning_for(path, 1, 20.0, 5.0, force=True)
app = Flask('t'); app.secret_key = 'x'
d = SimpleNamespace(app=app, DB_FILE=path, TAKE_PROFIT=0.05, STOP_LOSS=0.03,
                    rate_limit=lambda *a, **k: (lambda f: f),
                    _authenticated_wallet=lambda: session.get('wallet', ''))
bl.install(d)
client = app.test_client()
check('the learning API needs a connected wallet', client.get('/api/bot/learning').status_code == 401)
with client.session_transaction() as sess:
    sess['wallet'] = 'W1'
r = client.get('/api/bot/learning').get_json()
check('the bot page shows what was learned, from how many trades, with the log',
      r['ok'] and r['enabled'] and r['tp'] is not None and r['trades_analysed'] == 30
      and r['measuring'] and r['log'] and r['your_tp'] == 20.0)
check('the switch only accepts true/false', client.post('/api/bot/learning', json={'enabled': 'no'}).status_code == 400)
r = client.post('/api/bot/learning', json={'enabled': False}).get_json()
check('switching it off clears the applied changes immediately',
      r['ok'] and not r['enabled'] and r['tp'] is None
      and bl.tuning_for(path, 1, 20.0, 5.0) == {'tp': None, 'sl': None, 'score_floor': None, 'avoid': []})
r = client.post('/api/bot/learning', json={'enabled': True}).get_json()
check('switching it back on resumes learning', r['ok'] and r['enabled'])
page = open(os.path.join(ROOT, 'templates', 'auto_trading_bot.html'), encoding='utf-8').read()
check('the bot page has the Self-learning card, loads it and escapes what it shows',
      'id="bl-card"' in page and 'loadLearning()' in page and "esc(e.message)" in page and "esc(a)" in page)
raise SystemExit(0 if all(checks) else 1)
