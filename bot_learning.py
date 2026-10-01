"""Self-learning for the auto trading bot.

After every closed bot trade, each user's own recent bot trades are replayed
to see what would have worked better, and the bot applies what the evidence
supports -- automatically, with no one having to approve it:

- Take profit / stop loss. Every closed trade recorded its real intra-trade
  peak and trough (highest_price / lowest_price), so "what if the take profit
  had been lower" and "what if the stop loss had been tighter" can be
  replayed exactly on those trades. Ambiguous cases (both the new stop and
  the new target would have been touched, order unknown) are scored as the
  LOSS, and replayed exits pay the same execution cost the user's real exits
  paid. A WIDER target or stop is never replayed (nothing was recorded after
  a trade closed), so learning only ever makes the bot's exits earlier or
  tighter than the user's own settings, never riskier.
- Entry quality. A minimum entry score, and up to three kinds of entries to
  avoid (token age, market cap, buy/sell pressure, chain), when those trades
  lost money on their own.

Guards against learning noise:
- nothing changes before MIN_POSITIONS closed bot trades;
- a change must improve the replayed result overall AND in both the older
  and the newer half of the trades (it has to hold up over time);
- one change set at a time: after APPLY it is measured on the next
  EVAL_POSITIONS real trades and rolled back automatically if those did
  worse than before (that knob then rests for ROLLBACK_COOLDOWN_SEC);
- it never touches trade size, max positions, the daily loss limit, the
  crash exit or any safety filter, keeps at least half of the trades the bot
  would otherwise take, and the user can switch it off on the bot page.
"""
import json
import math
import sqlite3
import threading
import time
from statistics import median

MIN_POSITIONS = 20          # closed bot trades before anything is learned
WINDOW = 120                # most recent closed bot trades analysed
EVAL_POSITIONS = 15         # real trades a change is measured on before it is kept
ROLLBACK_MARGIN = 1.0       # %-points worse per trade than before -> roll back
ROLLBACK_COOLDOWN_SEC = 7 * 86400
MIN_GAIN_PER_TRADE = 0.75   # %-points per trade a replayed change must add
MIN_BUCKET = 8              # trades in a bucket before it can be avoided
MAX_AVOID = 3
TP_FLOOR, SL_FLOOR = 4.0, 2.0   # never tune exits tighter than this (%)
SCORE_FLOOR_BASE, SCORE_FLOOR_MAX = 5.0, 8.0
REFRESH_SEC = 300
# How clearly a group of entries must lose compared with the rest before it
# is cut (a two-sample z-score). Many groups are tested at once, so the bar
# is Bonferroni-high: on random trade histories with no real pattern, an
# entry rule is learned in well under 5% of cases.
Z_BUCKET = 3.0
Z_SCORE_FLOOR = 2.7

_lock = threading.Lock()
_cache = {}   # user_id -> (computed_at, tuning)


# ── reading closed trades ───────────────────────────────────────────────────

def _f(v):
    try:
        v = float(v)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _exit_kind(reason):
    r = (reason or '').upper()
    if r.startswith('TAKE PROFIT 1') or r.startswith('TAKE PROFIT 2') or r.startswith('TRAILING'):
        return 'tiered'
    if r.startswith('TAKE PROFIT'):
        return 'tp'
    if r.startswith('STOP LOSS'):
        return 'sl'
    return 'other'


def load_positions(conn, user_id, window=WINDOW):
    """The user's recent closed BOT positions, oldest first. A position sold
    in slices (staged take profit) is several trades rows; they are merged
    back into one position, its result weighted by the amount each slice
    sold."""
    rows = conn.execute(
        '''SELECT id, mint_address, token, opened_at, entry_price, exit_price, amount,
                  exit_reason, sl_pct, tp_pct, highest_price, lowest_price, entry_score,
                  entry_pair_age_minutes, entry_market_cap, entry_buy_sell_ratio, chain
           FROM trades
           WHERE user_id=? AND source='bot' AND entry_price>0 AND exit_price>0
           ORDER BY id DESC LIMIT ?''', (user_id, window * 4)).fetchall()
    groups = {}
    for r in reversed(rows):
        (tid, mint, token, opened_at, entry, exit_p, amount, reason, sl, tp, hi, lo,
         score, age, mcap, bsr, chain) = r
        key = (mint or token or '', opened_at or ('row', tid))
        g = groups.get(key)
        pnl = max(-100.0, min(500.0, (exit_p - entry) / entry * 100))
        w = _f(amount) or 0.0
        if g is None:
            g = groups[key] = {
                'last_id': tid, 'entry': entry, 'pnl_w': 0.0, 'w': 0.0, 'pnls': [],
                'reasons': [], 'sl': _f(sl), 'tp': _f(tp), 'hi': _f(hi), 'lo': _f(lo),
                'score': _f(score), 'age': _f(age), 'mcap': _f(mcap), 'bsr': _f(bsr),
                'chain': chain or 'solana'}
        g['last_id'] = max(g['last_id'], tid)
        g['pnls'].append(pnl)
        if w > 0:
            g['pnl_w'] += pnl * w
            g['w'] += w
        g['reasons'].append(reason)
        if _f(hi) is not None:
            g['hi'] = max(g['hi'] or 0, _f(hi))
        if _f(lo) is not None:
            g['lo'] = min(g['lo'] if g['lo'] is not None else _f(lo), _f(lo))
    out = []
    for g in sorted(groups.values(), key=lambda g: g['last_id']):
        pnl = g['pnl_w'] / g['w'] if g['w'] > 0 else sum(g['pnls']) / len(g['pnls'])
        kinds = {_exit_kind(r) for r in g['reasons']}
        kind = 'tiered' if 'tiered' in kinds or len(g['reasons']) > 1 else kinds.pop()
        e = g['entry']
        out.append({
            'pnl': pnl, 'kind': kind, 'sl': g['sl'], 'tp': g['tp'],
            'peak': (g['hi'] - e) / e * 100 if g['hi'] else None,
            'trough': (e - g['lo']) / e * 100 if g['lo'] else None,
            'score': g['score'], 'age': g['age'], 'mcap': g['mcap'], 'bsr': g['bsr'],
            'chain': g['chain']})
    return out[-window:]


# ── replaying exits ─────────────────────────────────────────────────────────

def _exec_costs(positions):
    """What the user's real exits cost beyond their trigger (slippage, a
    fast candle): replayed exits pay the same."""
    tp_c = [max(0.0, p['tp'] - p['pnl']) for p in positions if p['kind'] == 'tp' and p['tp']]
    sl_c = [max(0.0, -p['pnl'] - p['sl']) for p in positions if p['kind'] == 'sl' and p['sl']]
    tp_cost = min(5.0, median(tp_c)) if tp_c else 1.0
    sl_cost = min(10.0, median(sl_c)) if sl_c else 1.0
    return tp_cost, sl_cost


def replay(p, t, s, costs):
    """This one position's result had its take profit been t% and its stop
    loss s% (None = unchanged). Only ever tighter than what it really used."""
    tp_cost, sl_cost = costs
    t = t if (t is not None and p['tp'] and t < p['tp']) else None
    s = s if (s is not None and p['sl'] and s < p['sl']) else None
    if s is not None and p['trough'] is not None and p['trough'] >= s:
        return -s - sl_cost          # touched the tighter stop (assume first)
    if t is not None and p['peak'] is not None and p['peak'] >= t:
        return t - tp_cost           # touched the lower target
    return p['pnl']


def _z_worse(group, rest):
    """How many standard errors the group's average result sits below the
    rest's (0 when it does not, or when there is too little data)."""
    if len(group) < 2 or len(rest) < 2:
        return 0.0
    allp = [p['pnl'] for p in group + rest]
    m = sum(allp) / len(allp)
    sd = math.sqrt(sum((x - m) ** 2 for x in allp) / (len(allp) - 1))
    if sd <= 0:
        return 0.0
    mg = sum(p['pnl'] for p in group) / len(group)
    mr = sum(p['pnl'] for p in rest) / len(rest)
    return (mr - mg) / (sd * math.sqrt(1 / len(group) + 1 / len(rest)))


def _halves_improve(positions, outcome):
    mid = len(positions) // 2
    for part in (positions[:mid], positions[mid:]):
        if sum(outcome(p) for p in part) <= sum(p['pnl'] for p in part):
            return False
    return True


def tune_exits(positions, user_tp, user_sl):
    """Best (tp, sl) at or below the user's own settings, or None."""
    usable = [p for p in positions if p['kind'] != 'tiered' and p['tp'] and p['sl']
              and p['peak'] is not None and p['trough'] is not None]
    if len(usable) < MIN_POSITIONS or not user_tp or not user_sl:
        return None
    costs = _exec_costs(usable)
    base = sum(p['pnl'] for p in usable)
    lo_t, lo_s = max(TP_FLOOR, user_tp * 0.4), max(SL_FLOOR, user_sl * 0.5)
    ts = sorted({round(lo_t + (user_tp - lo_t) * i / 10, 1) for i in range(11)})
    ss = sorted({round(lo_s + (user_sl - lo_s) * i / 6, 1) for i in range(7)})
    best = None
    for t in ts:
        for s in ss:
            if t <= s + 1.0 or (t >= user_tp and s >= user_sl):
                continue
            total = sum(replay(p, t, s, costs) for p in usable)
            gain = total - base
            if gain / len(usable) < MIN_GAIN_PER_TRADE:
                continue
            if best is None or gain > best['gain']:
                best = {'tp': t, 'sl': s, 'gain': gain}
    if best and _halves_improve(usable, lambda p: replay(p, best['tp'], best['sl'], costs)):
        best['n'] = len(usable)
        best['per_trade'] = best['gain'] / len(usable)
        return best
    return None


# ── entry quality ───────────────────────────────────────────────────────────

BUCKETS = {
    'age': ('token age', [(0, 15, 'under 15 min old'), (15, 60, '15-60 min old'),
                          (60, 360, '1-6 h old'), (360, 1440, '6-24 h old'),
                          (1440, float('inf'), 'over a day old')]),
    'mcap': ('market cap', [(0, 100e3, 'market cap under $100K'),
                            (100e3, 500e3, 'market cap $100K-$500K'),
                            (500e3, 2e6, 'market cap $500K-$2M'),
                            (2e6, 10e6, 'market cap $2M-$10M'),
                            (10e6, float('inf'), 'market cap over $10M')]),
    'bsr': ('buy/sell pressure', [(0, 0.8, 'more sells than buys'),
                                  (0.8, 1.2, 'balanced buys and sells'),
                                  (1.2, 2.0, 'more buys than sells'),
                                  (2.0, float('inf'), 'buys over 2x sells')]),
}


def bucket_of(dim, value):
    if value is None:
        return None
    for lo, hi, label in BUCKETS[dim][1]:
        if lo <= value < hi:
            return label
    return None


def _position_buckets(p):
    out = {('chain', p['chain'])} if p['chain'] and p['chain'] != 'solana' else set()
    for dim in BUCKETS:
        b = bucket_of(dim, p[dim])
        if b:
            out.add((dim, b))
    return out


def tune_score_floor(positions):
    scored = [p for p in positions if p['score'] is not None]
    if len(scored) < MIN_POSITIONS:
        return None
    best = None
    f = SCORE_FLOOR_BASE + 0.5
    while f <= SCORE_FLOOR_MAX + 1e-9:
        cut = [p for p in scored if p['score'] < f]
        kept = [p for p in scored if p['score'] >= f]
        if (len(cut) >= MIN_BUCKET and len(kept) >= len(scored) / 2
                and sum(p['pnl'] for p in cut) / len(cut) <= -1.5
                and _z_worse(cut, kept) >= Z_SCORE_FLOOR):
            gain = -sum(p['pnl'] for p in cut)
            if gain / len(scored) >= MIN_GAIN_PER_TRADE and (best is None or gain > best['gain']):
                ok = _halves_improve(scored, lambda p, f=f: 0.0 if p['score'] < f else p['pnl'])
                if ok:
                    best = {'floor': round(f, 1), 'gain': gain, 'cut': len(cut), 'n': len(scored)}
        f += 0.5
    return best


def tune_avoid(positions):
    if len(positions) < MIN_POSITIONS:
        return []
    mid = len(positions) // 2
    stats = {}
    for i, p in enumerate(positions):
        for key in _position_buckets(p):
            s = stats.setdefault(key, {'n': 0, 'sum': 0.0, 'halves': [0.0, 0.0], 'hn': [0, 0]})
            s['n'] += 1
            s['sum'] += p['pnl']
            h = 0 if i < mid else 1
            s['halves'][h] += p['pnl']
            s['hn'][h] += 1
    def z(key):
        inside = [p for p in positions if key in _position_buckets(p)]
        outside = [p for p in positions if key not in _position_buckets(p)]
        return _z_worse(inside, outside)
    bad = [(k, s) for k, s in stats.items()
           if s['n'] >= MIN_BUCKET and s['sum'] < 0 and s['sum'] / s['n'] <= -2.0
           and min(s['hn']) >= 3 and max(s['halves']) < 0 and z(k) >= Z_BUCKET]
    bad.sort(key=lambda ks: ks[1]['sum'])
    chosen, removed = [], set()
    for (dim, label), s in bad:
        if len(chosen) >= MAX_AVOID:
            break
        would = {i for i, p in enumerate(positions) if (dim, label) in _position_buckets(p)} | removed
        if len(positions) - len(would) < len(positions) / 2:
            continue
        removed = would
        chosen.append({'dim': dim, 'label': label, 'n': s['n'],
                       'avg': round(s['sum'] / s['n'], 1)})
    return chosen


def analyse(positions, user_tp, user_sl):
    """What the evidence supports right now (pure; no side effects)."""
    out = {'tp': None, 'sl': None, 'score_floor': None, 'avoid': [], 'notes': []}
    ex = tune_exits(positions, user_tp, user_sl)
    if ex:
        if ex['tp'] < user_tp:
            out['tp'] = ex['tp']
        if ex['sl'] < user_sl:
            out['sl'] = ex['sl']
        out['notes'].append(
            f"Exits: take profit {ex['tp']:g}% / stop loss {ex['sl']:g}% would have added "
            f"{ex['per_trade']:+.1f}% per trade over your last {ex['n']} bot trades")
    sf = tune_score_floor(positions)
    if sf:
        out['score_floor'] = sf['floor']
        out['notes'].append(
            f"Entry score below {sf['floor']:g} lost money: {sf['cut']} of {sf['n']} trades")
    out['avoid'] = tune_avoid(positions)
    for a in out['avoid']:
        name = a['label'] if a['dim'] != 'chain' else a['label'].title() + ' tokens'
        out['notes'].append(f"Avoiding {name}: {a['n']} trades averaged {a['avg']:+.1f}%")
    return out


# ── state: apply, measure, roll back ────────────────────────────────────────

def _ensure(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS bot_learning (
        user_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL DEFAULT '{}', updated_at REAL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS bot_learning_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        at REAL NOT NULL, message TEXT NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_bot_learning_log_user ON bot_learning_log(user_id, id)')


def _load(conn, user_id):
    row = conn.execute('SELECT enabled, state FROM bot_learning WHERE user_id=?', (user_id,)).fetchone()
    if not row:
        return True, {}
    try:
        return bool(row[0]), json.loads(row[1] or '{}')
    except ValueError:
        return bool(row[0]), {}


def _save(conn, user_id, enabled, state):
    conn.execute('''INSERT INTO bot_learning (user_id, enabled, state, updated_at) VALUES (?,?,?,?)
                    ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled,
                    state=excluded.state, updated_at=excluded.updated_at''',
                 (user_id, int(enabled), json.dumps(state), time.time()))


def _log(conn, user_id, message):
    conn.execute('INSERT INTO bot_learning_log (user_id, at, message) VALUES (?,?,?)',
                 (user_id, time.time(), message[:400]))
    conn.execute('''DELETE FROM bot_learning_log WHERE user_id=? AND id NOT IN
                    (SELECT id FROM bot_learning_log WHERE user_id=? ORDER BY id DESC LIMIT 50)''',
                 (user_id, user_id))


KNOBS = ('tp', 'sl', 'score_floor', 'avoid')


def _describe(changes):
    bits = []
    if 'tp' in changes:
        bits.append(f"take profit -> {changes['tp']:g}%" if changes['tp'] is not None else 'take profit back to your setting')
    if 'sl' in changes:
        bits.append(f"stop loss -> {changes['sl']:g}%" if changes['sl'] is not None else 'stop loss back to your setting')
    if 'score_floor' in changes:
        bits.append(f"minimum entry score -> {changes['score_floor']:g}" if changes['score_floor'] else 'minimum entry score back to normal')
    if 'avoid' in changes:
        bits.append('avoiding ' + ', '.join(a['label'] for a in changes['avoid']) if changes['avoid'] else 'no entries avoided')
    return '; '.join(bits)


def step(conn, user_id, user_tp, user_sl, now=None):
    """Advance one user's learning: measure a pending change (keep or roll
    back), otherwise apply what the evidence supports. Returns the state."""
    now = now or time.time()
    _ensure(conn)
    enabled, st = _load(conn, user_id)
    active = st.get('active') or {}
    if not enabled:
        return enabled, st
    positions = load_positions(conn, user_id)
    total = len(positions)
    count = conn.execute("SELECT COUNT(*) FROM trades WHERE user_id=? AND source='bot'",
                         (user_id,)).fetchone()[0]
    pending = st.get('pending')
    if pending:
        n_since = _positions_since(conn, user_id, pending['trade_id'])
        since = positions[-n_since:] if n_since else []
        if len(since) >= EVAL_POSITIONS:
            after = sum(p['pnl'] for p in since[:EVAL_POSITIONS]) / EVAL_POSITIONS
            if after < pending['before_avg'] - ROLLBACK_MARGIN:
                st['active'] = pending['previous']
                cool = st.setdefault('cooldown', {})
                for k in pending['changes']:
                    cool[k] = now + ROLLBACK_COOLDOWN_SEC
                _log(conn, user_id, f"Rolled back ({_describe(pending['changes'])}): the next "
                     f"{EVAL_POSITIONS} trades averaged {after:+.1f}% vs {pending['before_avg']:+.1f}% before")
            else:
                _log(conn, user_id, f"Kept ({_describe(pending['changes'])}): the next "
                     f"{EVAL_POSITIONS} trades averaged {after:+.1f}% vs {pending['before_avg']:+.1f}% before")
            st.pop('pending', None)
        _save(conn, user_id, enabled, st)
        return enabled, st
    if total < MIN_POSITIONS:
        _save(conn, user_id, enabled, st)
        return enabled, st
    want = analyse(positions, user_tp, user_sl)
    cool = {k: v for k, v in (st.get('cooldown') or {}).items() if v > now}
    st['cooldown'] = cool
    changes = {}
    for k in KNOBS:
        new = want[k]
        if k in cool:
            continue
        old = active.get(k) if k != 'avoid' else (active.get('avoid') or [])
        if k == 'avoid':
            if [a['label'] for a in new] != [a['label'] for a in old]:
                changes[k] = new
        elif new != old and new is not None:
            changes[k] = new
    if changes:
        last_id = conn.execute("SELECT MAX(id) FROM trades WHERE user_id=? AND source='bot'",
                               (user_id,)).fetchone()[0]
        recent = positions[-20:]
        st['pending'] = {'changes': changes, 'previous': dict(active), 'applied_at': now,
                         'trade_id': last_id,
                         'before_avg': round(sum(p['pnl'] for p in recent) / len(recent), 2)}
        active = dict(active)
        active.update(changes)
        st['active'] = active
        st['notes'] = want['notes']
        _log(conn, user_id, 'Learned from your last %d bot trades: %s' % (total, _describe(changes)))
    st['analysed_at'] = now
    st['trades_seen'] = count
    _save(conn, user_id, enabled, st)
    return enabled, st


def _positions_since(conn, user_id, trade_id):
    if trade_id is None:
        return 0
    rows = conn.execute(
        "SELECT DISTINCT COALESCE(mint_address, token), opened_at FROM trades "
        "WHERE user_id=? AND source='bot' AND id>? AND entry_price>0 AND exit_price>0",
        (user_id, trade_id)).fetchall()
    return len(rows)


# ── what the bot loop uses ──────────────────────────────────────────────────

def tuning_for(db_file, user_id, user_tp, user_sl, force=False):
    """The adjustments the bot applies right now: {'tp','sl','score_floor',
    'avoid'} (None/[] = use the user's own settings). Re-analysed at most
    every REFRESH_SEC, or right away after a trade closed (invalidate())."""
    now = time.time()
    with _lock:
        hit = _cache.get(user_id)
        if hit and not force and now - hit[0] < REFRESH_SEC:
            return hit[1]
    try:
        conn = sqlite3.connect(db_file, timeout=8)
        try:
            enabled, st = step(conn, user_id, user_tp, user_sl, now)
            conn.commit()
        finally:
            conn.close()
    except Exception as e:  # learning must never stop the bot
        print(f'[bot-learning] user {user_id}: {e}', flush=True)
        enabled, st = False, {}
    active = (st.get('active') or {}) if enabled else {}
    tuning = {
        'tp': active.get('tp') if active.get('tp') and active['tp'] < user_tp else None,
        'sl': active.get('sl') if active.get('sl') and active['sl'] < user_sl else None,
        'score_floor': active.get('score_floor'),
        'avoid': list(active.get('avoid') or []),
    }
    if tuning['tp'] is not None and tuning['sl'] is not None and tuning['tp'] <= tuning['sl']:
        tuning['tp'] = tuning['sl'] = None
    with _lock:
        _cache[user_id] = (now, tuning)
    return tuning


def invalidate(user_id):
    with _lock:
        _cache.pop(user_id, None)


def avoid_reason(tuning, chain='solana', pair_age_minutes=None, market_cap=None, buy_sell_ratio=None):
    """The learned rule this candidate falls under, or ''."""
    for a in (tuning or {}).get('avoid') or []:
        dim, label = a.get('dim'), a.get('label')
        if dim == 'chain' and chain == label:
            return f'{chain.title()} tokens'
        value = {'age': pair_age_minutes, 'mcap': market_cap, 'bsr': buy_sell_ratio}.get(dim)
        if dim in BUCKETS and bucket_of(dim, value) == label:
            return label
    return ''


def candidate_features(token):
    """Entry features of a scanned token, computed exactly like the trade
    snapshot (_snapshot_entry_risk) records them, so a learned rule matches
    the same tokens it was learned from."""
    created_ms = token.get('pairCreatedAt', 0) or 0
    buys = float(token.get('txns_buys', 0) or 0)
    sells = float(token.get('txns_sells', 0) or 0)
    return {
        'pair_age_minutes': (time.time() - created_ms / 1000) / 60 if created_ms > 0 else None,
        'market_cap': float(token.get('market_cap', 0) or token.get('fdv', 0) or 0) or None,
        'buy_sell_ratio': (buys / sells) if sells > 0 else None,
    }


# ── bot page API ────────────────────────────────────────────────────────────

def install(d):
    from flask import jsonify, request
    app = d.app
    if getattr(app, '_orca_bot_learning_installed', False):
        return
    app._orca_bot_learning_installed = True
    conn = sqlite3.connect(d.DB_FILE, timeout=8)
    try:
        _ensure(conn)
        conn.commit()
    finally:
        conn.close()

    def _user(wallet):
        conn = sqlite3.connect(d.DB_FILE, timeout=8)
        try:
            row = conn.execute('SELECT id, take_profit, stop_loss FROM users WHERE wallet_address=?',
                               (wallet,)).fetchone()
        finally:
            conn.close()
        return row

    @app.route('/api/bot/learning', methods=['GET', 'POST'])
    @d.rate_limit(30, 60)
    def bot_learning_api():
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify({'ok': False, 'msg': 'Connect your wallet'}), 401
        row = _user(wallet)
        if not row:
            return jsonify({'ok': False, 'msg': 'Account not found'}), 404
        user_id = row[0]
        user_tp = float(row[1]) if row[1] is not None else d.TAKE_PROFIT * 100
        user_sl = float(row[2]) if row[2] is not None else d.STOP_LOSS * 100
        conn = sqlite3.connect(d.DB_FILE, timeout=8)
        try:
            _ensure(conn)
            enabled, st = _load(conn, user_id)
            if request.method == 'POST':
                body = request.get_json(silent=True) or {}
                if not isinstance(body.get('enabled'), bool):
                    return jsonify({'ok': False, 'msg': 'enabled must be true or false'}), 400
                enabled = body['enabled']
                if not enabled:
                    st.pop('pending', None)
                _save(conn, user_id, enabled, st)
                _log(conn, user_id, 'Self-learning switched ' + ('on' if enabled else 'off')
                     + (' — the bot uses your own settings only' if not enabled else ''))
                conn.commit()
                invalidate(user_id)
            log = conn.execute('SELECT at, message FROM bot_learning_log WHERE user_id=? '
                               'ORDER BY id DESC LIMIT 8', (user_id,)).fetchall()
            seen = len(load_positions(conn, user_id))
        finally:
            conn.close()
        active = (st.get('active') or {}) if enabled else {}
        return jsonify({
            'ok': True, 'enabled': enabled,
            'trades_analysed': seen, 'needs': MIN_POSITIONS,
            'measuring': bool(st.get('pending')) and enabled,
            'your_tp': user_tp, 'your_sl': user_sl,
            'tp': active.get('tp') if active.get('tp') and active['tp'] < user_tp else None,
            'sl': active.get('sl') if active.get('sl') and active['sl'] < user_sl else None,
            'score_floor': active.get('score_floor'),
            'avoid': [a.get('label') for a in active.get('avoid') or []],
            'notes': st.get('notes') or [],
            'log': [{'at': int(a), 'message': m} for a, m in log],
        })
