"""Home feed "Trending now" hero card: one token, while it is trending.

WHAT COUNTS AS TRENDING
The candidates are the Live Market scanner's own tokens (DexScreener
boosted/trending, already cached every 15s), so this adds no upstream load.
A token qualifies on real, hard-to-fake market activity -- all of:

    24h price change   >= +25%
    24h volume         >= $50K
    liquidity          >= $20K
    market cap         >= $50K
    buyers outnumber sellers, with a buy share between 55% and 97%
      (100% buys is what a sell-blocking honeypot looks like)

and it must pass the same chain-aware scam filter the Live Market list uses.
A token the surge radar is flagging right now (volume + transactions
exploding within minutes) ranks first; otherwise the most traded one wins.

WHEN IT LEAVES
The card shows the current hero for as long as it is still trending, judged
on a slightly looser bar (hysteresis) so it does not flicker in and out on
one noisy refresh. When nothing qualifies the endpoint returns no token and
the card disappears from the feed.

VOTES AND LIKES
One bull/bear vote and one like per member per token (tapping again takes it
back). Only tokens that have actually been the hero can be voted on, so the
tables cannot be filled with arbitrary strings. This is sentiment, not
advice, and it never touches a wallet.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from contextlib import contextmanager

from flask import jsonify, request

ENTER = {'change': 25.0, 'volume': 50_000.0, 'liquidity': 20_000.0, 'mcap': 50_000.0,
         'buy_min': 0.55, 'buy_max': 0.97}
STAY = {'change': 15.0, 'volume': 30_000.0, 'liquidity': 15_000.0, 'mcap': 30_000.0,
        'buy_min': 0.50, 'buy_max': 0.985}
CACHE_SECONDS = 20
MAX_SAFETY_CHECKS = 6
_MINT_RE = re.compile(r'^(?:[1-9A-HJ-NP-Za-km-z]{32,44}|0x[0-9a-fA-F]{40})$')

_lock = threading.Lock()
_state = {'at': 0.0, 'token': None, 'mint': None, 'recent': {}}   # recent: mint -> last time it was the hero


def _f(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _buy_share(t):
    buys, sells = _f(t.get('buys_24h')), _f(t.get('sells_24h'))
    total = buys + sells
    return (buys / total) if total else 0.0


def qualifies(t, bar=ENTER) -> bool:
    """Pure: does this scanner token meet the trending bar?"""
    if not t or _f(t.get('price_usd')) <= 0:
        return False
    share = _buy_share(t)
    return (_f(t.get('price_change_24h')) >= bar['change']
            and _f(t.get('volume_24h')) >= bar['volume']
            and _f(t.get('liquidity_usd')) >= bar['liquidity']
            and _f(t.get('market_cap')) >= bar['mcap']
            and _f(t.get('buys_24h')) > _f(t.get('sells_24h'))
            and bar['buy_min'] <= share <= bar['buy_max'])


def _surging(d) -> dict:
    try:
        import surge_radar
        return {s['mint']: s for s in surge_radar.current_surges() if not s.get('cooling')}
    except Exception:
        return {}


def _safe(d, t) -> bool:
    try:
        safety = d._scanner_get_safety(t['mint'], t.get('chain') or 'solana', False)
        return bool(d._scanner_token_passes_scam_filter(t, safety))
    except Exception:
        return False   # unknown safety is never promoted to the top of the feed


def _public(t, surge) -> dict:
    return {
        'mint': t['mint'], 'symbol': t.get('symbol') or '', 'name': t.get('name') or '',
        'chain': (t.get('chain') or 'solana').lower(), 'pair_address': t.get('pair_address') or '',
        'image_url': t.get('image_url') or '',
        'price_usd': _f(t.get('price_usd')), 'price_change_24h': _f(t.get('price_change_24h')),
        'volume_24h': _f(t.get('volume_24h')), 'liquidity_usd': _f(t.get('liquidity_usd')),
        'market_cap': _f(t.get('market_cap')),
        'buys_24h': int(_f(t.get('buys_24h'))), 'sells_24h': int(_f(t.get('sells_24h'))),
        'surging': bool(surge),
    }


def pick(d, candidates, surges, now=None, safe=None) -> dict | None:
    """Choose the hero from scanner candidates. Keeps the current hero while it
    still clears the looser STAY bar; otherwise the best ENTER-qualified,
    scam-filtered token; otherwise None (the card disappears)."""
    now = now or time.time()
    safe = safe or (lambda t: _safe(d, t))
    by_mint = {t.get('mint'): t for t in candidates if t.get('mint')}
    current = _state.get('mint')
    if current and current in by_mint and qualifies(by_mint[current], STAY):
        t = by_mint[current]
        return _public(t, surges.get(current))
    pool = [t for t in candidates if qualifies(t, ENTER)]
    pool.sort(key=lambda t: (t.get('mint') in surges,
                             _f((surges.get(t.get('mint')) or {}).get('score')),
                             _f(t.get('volume_24h')) * _buy_share(t)), reverse=True)
    for t in pool[:MAX_SAFETY_CHECKS]:
        if safe(t):
            return _public(t, surges.get(t['mint']))
    return None


def current_hero(d) -> dict | None:
    now = time.time()
    with _lock:
        if now - _state['at'] < CACHE_SECONDS:
            return _state['token']
    try:
        candidates = list(d._get_scanner_cached())
    except Exception:
        candidates = []
    token = pick(d, candidates, _surging(d), now)
    with _lock:
        _state.update(at=now, token=token, mint=token['mint'] if token else None)
        if token:
            _state['recent'][token['mint']] = now
        for m in [m for m, ts in _state['recent'].items() if now - ts > 6 * 3600]:
            _state['recent'].pop(m, None)
    return token


@contextmanager
def _db(d):
    """Commit on success, roll back on error, always close."""
    conn = sqlite3.connect(d.DB_FILE, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _schema(d):
    with _db(d) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS trending_hero_votes (
            mint TEXT NOT NULL, user_id INTEGER NOT NULL, vote INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (mint, user_id))''')
        conn.execute('''CREATE TABLE IF NOT EXISTS trending_hero_likes (
            mint TEXT NOT NULL, user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (mint, user_id))''')


def _uid(d):
    wallet = d._authenticated_wallet()
    if not wallet:
        return None
    with _db(d) as conn:
        row = conn.execute('SELECT id FROM users WHERE wallet_address=?', (wallet,)).fetchone()
    return int(row['id']) if row else None


def social(d, mint, uid=None) -> dict:
    with _db(d) as conn:
        bull = conn.execute('SELECT COUNT(*) FROM trending_hero_votes WHERE mint=? AND vote=1', (mint,)).fetchone()[0]
        bear = conn.execute('SELECT COUNT(*) FROM trending_hero_votes WHERE mint=? AND vote=-1', (mint,)).fetchone()[0]
        likes = conn.execute('SELECT COUNT(*) FROM trending_hero_likes WHERE mint=?', (mint,)).fetchone()[0]
        mine_vote, mine_like = 0, False
        if uid:
            r = conn.execute('SELECT vote FROM trending_hero_votes WHERE mint=? AND user_id=?', (mint, uid)).fetchone()
            mine_vote = int(r['vote']) if r else 0
            mine_like = conn.execute('SELECT 1 FROM trending_hero_likes WHERE mint=? AND user_id=?',
                                     (mint, uid)).fetchone() is not None
    return {'bull': int(bull), 'bear': int(bear), 'likes': int(likes),
            'my_vote': mine_vote, 'liked': mine_like}


def _votable(mint) -> bool:
    if not isinstance(mint, str) or not _MINT_RE.match(mint):
        return False
    with _lock:
        return mint in _state['recent'] or mint == _state.get('mint')


def install(d):
    app = d.app
    if getattr(app, '_orca_trending_hero_installed', False):
        return
    app._orca_trending_hero_installed = True
    _schema(d)

    @app.get('/api/home/trending-hero')
    @d.rate_limit(60, 60)
    def trending_hero():
        token = current_hero(d)
        if not token:
            return jsonify({'ok': True, 'token': None})
        return jsonify({'ok': True, 'token': token, 'social': social(d, token['mint'], _uid(d))})

    @app.post('/api/home/trending-hero/vote')
    @d.rate_limit(30, 60)
    def trending_hero_vote():
        uid = _uid(d)
        if uid is None:
            return jsonify({'ok': False, 'msg': 'Sign in to vote'}), 401
        body = request.get_json(silent=True) or {}
        mint, vote = body.get('mint'), {'bull': 1, 'bear': -1}.get(body.get('vote'))
        if vote is None:
            return jsonify({'ok': False, 'msg': 'Vote bull or bear'}), 400
        if not _votable(mint):
            return jsonify({'ok': False, 'msg': 'This token is no longer trending'}), 409
        with _db(d) as conn:
            r = conn.execute('SELECT vote FROM trending_hero_votes WHERE mint=? AND user_id=?', (mint, uid)).fetchone()
            if r and int(r['vote']) == vote:
                conn.execute('DELETE FROM trending_hero_votes WHERE mint=? AND user_id=?', (mint, uid))
            else:
                conn.execute('INSERT OR REPLACE INTO trending_hero_votes (mint, user_id, vote) VALUES (?,?,?)',
                             (mint, uid, vote))
        return jsonify({'ok': True, 'social': social(d, mint, uid)})

    @app.post('/api/home/trending-hero/like')
    @d.rate_limit(30, 60)
    def trending_hero_like():
        uid = _uid(d)
        if uid is None:
            return jsonify({'ok': False, 'msg': 'Sign in to like'}), 401
        mint = (request.get_json(silent=True) or {}).get('mint')
        if not _votable(mint):
            return jsonify({'ok': False, 'msg': 'This token is no longer trending'}), 409
        with _db(d) as conn:
            cur = conn.execute('DELETE FROM trending_hero_likes WHERE mint=? AND user_id=?', (mint, uid))
            if cur.rowcount == 0:
                conn.execute('INSERT INTO trending_hero_likes (mint, user_id) VALUES (?,?)', (mint, uid))
        return jsonify({'ok': True, 'social': social(d, mint, uid)})
