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

ANNOUNCING IT
When a token becomes the hero, every member who has notifications on gets an
in-app notification and a phone push ("$WOJAK is trending"), tagged
TREND_PUSH_TAG so a newer one replaces an older one on the phone. Tapping it
opens the home feed scrolled to the card (TREND_LINK). Once the card is
actually on screen in the app, the app closes that phone notification and
marks the in-app one read (POST /api/home/trending-hero/seen). A background
loop checks every ANNOUNCE_POLL_SECONDS, so it does not wait for a visitor.
Limits, so it never becomes noise: each token is announced at most once per
ANNOUNCE_REPEAT_HOURS, and at most one announcement per ANNOUNCE_MIN_GAP
seconds across all tokens. The claim is a database row inserted in one
transaction, so a restart or a second worker cannot announce twice.

VOTES AND LIKES
One bull/bear vote and one like per member per token (tapping again takes it
back). Only tokens that have actually been the hero can be voted on, so the
tables cannot be filled with arbitrary strings. This is sentiment, not
advice, and it never touches a wallet.
"""
from __future__ import annotations

import os
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
TREND_PUSH_TAG = 'orc-trending'
TREND_LINK = '/?trending=1#trending'
ANNOUNCE_POLL_SECONDS = 60
ANNOUNCE_REPEAT_HOURS = 12
ANNOUNCE_MIN_GAP = 30 * 60
MAX_SAFETY_CHECKS = 6
_MINT_RE = re.compile(r'^(?:[1-9A-HJ-NP-Za-km-z]{32,44}|0x[0-9a-fA-F]{40})$')

_lock = threading.Lock()
_state = {'at': 0.0, 'token': None, 'mint': None, 'recent': {},   # recent: mint -> last time it was the hero
          'since': 0.0}                                             # when the current hero started trending


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
        if token and token['mint'] != _state.get('mint'):
            _state['since'] = now
        if token:
            # When it started trending: the home feed shows the card as a post
            # with this as its time ("12m").
            token = dict(token, trending_since=int(_state['since'] or now))
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
        conn.execute('''CREATE TABLE IF NOT EXISTS trending_hero_announcements (
            mint TEXT PRIMARY KEY, announced_at REAL NOT NULL)''')


def _fmt_usd(v):
    v = _f(v)
    for cut, suf in ((1e9, 'B'), (1e6, 'M'), (1e3, 'K')):
        if v >= cut:
            n = v / cut
            return '$' + (f'{n:.1f}'.rstrip('0').rstrip('.') if n < 100 else f'{n:.0f}') + suf
    return f'${v:.0f}'


def announcement_text(t) -> tuple:
    """(title, body) for the push: ticker first, then the numbers."""
    sym = (t.get('symbol') or '?').upper()
    sym = sym if len(sym) <= 12 else sym[:11] + '…'
    chain = {'solana': 'Solana', 'bsc': 'BNB Chain', 'base': 'Base', 'arbitrum': 'Arbitrum',
             'polygon': 'Polygon', 'robinhood': 'Robinhood Chain'}.get(t.get('chain'), (t.get('chain') or '').title())
    title = f'🔥 ${sym} is trending'
    body = f"{_f(t.get('price_change_24h')):+.1f}% · {_fmt_usd(t.get('volume_24h'))} volume · {chain}"
    return title, body


def _claim_announcement(d, mint, now) -> bool:
    """Atomically reserve the right to announce `mint` now. False when this
    token was announced within ANNOUNCE_REPEAT_HOURS, or any token within
    ANNOUNCE_MIN_GAP."""
    with _db(d) as conn:
        conn.execute('BEGIN IMMEDIATE')
        last_any = conn.execute('SELECT MAX(announced_at) FROM trending_hero_announcements').fetchone()[0]
        if last_any and now - float(last_any) < ANNOUNCE_MIN_GAP:
            return False
        row = conn.execute('SELECT announced_at FROM trending_hero_announcements WHERE mint=?', (mint,)).fetchone()
        if row and now - float(row['announced_at']) < ANNOUNCE_REPEAT_HOURS * 3600:
            return False
        conn.execute('INSERT OR REPLACE INTO trending_hero_announcements (mint, announced_at) VALUES (?,?)',
                     (mint, now))
    return True


def announce(d, token, now=None) -> int:
    """Notify members that `token` is trending. Returns how many members got
    the in-app notification (0 when throttled). Never raises."""
    if not token or not token.get('mint'):
        return 0
    now = now or time.time()
    try:
        if not _claim_announcement(d, token['mint'], now):
            return 0
        title, body = announcement_text(token)
        content = f'{title} · {body}'
        with _db(d) as conn:
            # Only the newest trending alert matters: older ones point at a
            # card that has already been replaced.
            conn.execute("UPDATE notifications SET is_read=1 WHERE type='trending' AND is_read=0")
            cur = conn.execute(
                "INSERT INTO notifications (user_id, type, content, link, actor_wallet) "
                "SELECT id, 'trending', ?, ?, NULL FROM users WHERE COALESCE(pref_notifications, 1) = 1",
                (content, TREND_LINK))
            count = cur.rowcount
            push_ids = [r[0] for r in conn.execute(
                'SELECT DISTINCT u.id FROM users u JOIN push_subscriptions p ON p.user_id = u.id '
                'WHERE COALESCE(u.pref_notifications, 1) = 1').fetchall()]
        icon = (token.get('image_url') or '').strip()
        if not icon.startswith('https://') or len(icon) > 500:
            icon = ''
        if push_ids:
            d._send_push_notifications_bulk(push_ids, title, body, TREND_LINK, icon, TREND_PUSH_TAG)
        print(f"[trending-hero] announced ${token.get('symbol')} to {count} member(s), "
              f"{len(push_ids)} with push", flush=True)
        return count
    except Exception as e:
        print(f'[trending-hero] announcement failed: {type(e).__name__}: {e}', flush=True)
        return 0


def _announce_loop(d):
    time.sleep(90)   # let the scanner warm up after a restart
    while True:
        try:
            token = current_hero(d)
            if token:
                announce(d, token)
        except Exception as e:
            print(f'[trending-hero] loop error: {type(e).__name__}', flush=True)
        time.sleep(ANNOUNCE_POLL_SECONDS)


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

    @app.post('/api/home/trending-hero/seen')
    @d.rate_limit(30, 60)
    def trending_hero_seen():
        """The card is on screen: the trending alert has been seen."""
        uid = _uid(d)
        if uid is None:
            return jsonify({'ok': True, 'marked': 0})
        with _db(d) as conn:
            cur = conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND type='trending' AND is_read=0",
                               (uid,))
        return jsonify({'ok': True, 'marked': cur.rowcount})

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

    # Announce new trending tokens even when nobody has the home page open.
    if os.environ.get('ORCAGENT_TRENDING_ALERTS', '1') != '0':
        threading.Thread(target=_announce_loop, args=(d,), name='orca-trending-alerts',
                         daemon=True).start()
