"""Private, opt-in, one-shot Solana price alerts; never execute trades.

SQLite claims serialize workers and atomically store each fired notification.
Prices use the existing DexScreener cache and backoff. No keys or balances are
needed. Browser responses are private; alert ownership comes from the session.
"""
from __future__ import annotations

import math
import os
import sqlite3
import threading
import time
from urllib.parse import urlencode

MAX_WATCHED = 100
MAX_ALERTS = 20
POLL_SECONDS = 30


def initialize(path):
    with sqlite3.connect(path, timeout=10) as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS watch_price_alerts (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            mint TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('above','below')),
            target REAL NOT NULL CHECK(target>0), active INTEGER NOT NULL DEFAULT 1,
            created_at REAL NOT NULL, fired_at REAL, observed_price REAL
        );
        CREATE INDEX IF NOT EXISTS idx_watch_alert_owner ON watch_price_alerts(user_id,active);
        CREATE INDEX IF NOT EXISTS idx_watch_alert_mint ON watch_price_alerts(mint,active);
        CREATE TABLE IF NOT EXISTS watch_alert_poll (
            id INTEGER PRIMARY KEY CHECK(id=1), next_at REAL NOT NULL, cursor TEXT NOT NULL
        );
        INSERT OR IGNORE INTO watch_alert_poll VALUES(1,0,'');
        ''')


def positive_price(value):
    if isinstance(value, bool):
        raise ValueError('Enter a positive USD price')
    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Enter a positive USD price') from None
    if not math.isfinite(price) or price < 1e-15 or price > 1e12:
        raise ValueError('Enter a USD price between 0.000000000000001 and 1 trillion')
    return price


def create_alert(path, uid, mint, direction, target, now=None):
    target = positive_price(target)
    if direction not in ('above', 'below'):
        raise ValueError('Choose above or below')
    now = time.time() if now is None else now
    with sqlite3.connect(path, timeout=10) as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM watchlist WHERE user_id=? AND token_address=?', (uid, mint)).fetchone():
            raise ValueError('Add this token to your watchlist first')
        c.execute('DELETE FROM watch_price_alerts WHERE user_id=? AND NOT EXISTS '
                  '(SELECT 1 FROM watchlist w WHERE w.user_id=watch_price_alerts.user_id '
                  'AND w.token_address=watch_price_alerts.mint)', (uid,))
        duplicate = c.execute('SELECT id FROM watch_price_alerts WHERE user_id=? AND mint=? '
                              'AND direction=? AND target=? AND active=1', (uid, mint, direction, target)).fetchone()
        if duplicate:
            return duplicate[0]
        if c.execute('SELECT COUNT(*) FROM watch_price_alerts WHERE user_id=? AND active=1', (uid,)).fetchone()[0] >= MAX_ALERTS:
            raise ValueError('You can have up to 20 active alerts')
        # Retain the latest 100 completed alerts per user, rather than growing forever.
        c.execute('DELETE FROM watch_price_alerts WHERE user_id=? AND active=0 AND id NOT IN '
                  '(SELECT id FROM watch_price_alerts WHERE user_id=? AND active=0 ORDER BY id DESC LIMIT 100)', (uid, uid))
        return c.execute('INSERT INTO watch_price_alerts(user_id,mint,direction,target,created_at) '
                         'VALUES(?,?,?,?,?)', (uid, mint, direction, target, now)).lastrowid


def alert_list(path, uid):
    with sqlite3.connect(path, timeout=10) as c:
        rows = c.execute('SELECT a.id,a.mint,a.direction,a.target,a.active,a.fired_at,a.observed_price '
                         'FROM watch_price_alerts a JOIN watchlist w ON w.user_id=a.user_id '
                         'AND w.token_address=a.mint WHERE a.user_id=? ORDER BY a.id DESC LIMIT 120', (uid,)).fetchall()
    return [dict(id=r[0], mint=r[1], direction=r[2], target=r[3], active=bool(r[4]),
                 fired_at=r[5], observed_price=r[6]) for r in rows]


def claim_batch(path, now=None):
    """At most one poll across all workers; rotate batches so every mint is checked."""
    now = time.time() if now is None else now
    with sqlite3.connect(path, timeout=10) as c:
        c.execute('BEGIN IMMEDIATE')
        next_at, cursor = c.execute('SELECT next_at,cursor FROM watch_alert_poll WHERE id=1').fetchone()
        if next_at > now:
            return []
        query = ('SELECT DISTINCT a.mint FROM watch_price_alerts a JOIN watchlist w '
                 'ON w.user_id=a.user_id AND w.token_address=a.mint WHERE a.active=1 ')
        mints = [r[0] for r in c.execute(query + 'AND a.mint>? ORDER BY a.mint LIMIT 30', (cursor,))]
        if not mints:
            mints = [r[0] for r in c.execute(query + 'ORDER BY a.mint LIMIT 30')]
        c.execute('UPDATE watch_alert_poll SET next_at=?,cursor=? WHERE id=1',
                  (now + 60, mints[-1] if mints else ''))
        return mints


def fire_prices(path, prices, observed_at, now=None):
    """Notification and one-shot status commit together, including under concurrency."""
    now = time.time() if now is None else now
    if not math.isfinite(observed_at) or not 0 <= now - observed_at <= 90:
        return []
    fired = []
    with sqlite3.connect(path, timeout=10) as c:
        c.execute('BEGIN IMMEDIATE')
        rows = c.execute('SELECT a.id,a.user_id,a.mint,a.direction,a.target,w.symbol '
                         'FROM watch_price_alerts a JOIN watchlist w ON w.user_id=a.user_id '
                         'AND w.token_address=a.mint WHERE a.active=1').fetchall()
        for aid, uid, mint, direction, target, symbol in rows:
            try:
                price = positive_price(prices.get(mint))
            except ValueError:
                continue
            if not (price >= target if direction == 'above' else price <= target):
                continue
            link = '/live-market?' + urlencode({'mint': mint})
            label = (symbol or mint[:8])[:20]
            content = f'{label} reached your {direction} ${target:.10g} alert. Observed price: ${price:.10g} USD.'
            c.execute('UPDATE watch_price_alerts SET active=0,fired_at=?,observed_price=? WHERE id=? AND active=1',
                      (now, price, aid))
            c.execute('INSERT INTO notifications(user_id,type,content,link) VALUES(?,?,?,?)',
                      (uid, 'price_alert', content, link))
            fired.append((uid, aid, content, link))
    return fired


def poll(d, now=None):
    now = time.time() if now is None else now
    mints = claim_batch(d.DB_FILE, now)
    if not mints:
        return
    url = 'https://api.dexscreener.com/latest/dex/tokens/' + ','.join(mints)
    try:
        response = d._dex_get(url, timeout=8, ttl_override=30)
        # _dex_get can serve stale data during a provider outage. Never trigger from it.
        cached_at = d._dex_resp_cache.get(url, (0, ''))[0]
        if not response or response.status_code != 200 or not 0 <= time.time() - cached_at <= 90:
            return
        best = {}
        for pair in response.json().get('pairs') or []:
            mint = (pair.get('baseToken') or {}).get('address')
            if mint not in mints or pair.get('chainId') != 'solana':
                continue
            liquidity = float((pair.get('liquidity') or {}).get('usd') or 0)
            if not math.isfinite(liquidity) or liquidity <= 0:
                continue
            try:
                price = positive_price(pair.get('priceUsd'))
            except ValueError:
                continue
            if mint not in best or liquidity > best[mint][0]:
                best[mint] = (liquidity, price)
        for uid, aid, content, link in fire_prices(d.DB_FILE, {m: p[1] for m, p in best.items()}, cached_at):
            # Existing push subscriptions are opt-in; in-app receipt is always durable.
            d._send_push_notification(uid, 'Your OrcAgent price alert', content, link, tag=f'price-alert-{aid}')
    except (ValueError, TypeError, sqlite3.Error):
        d.app.logger.warning('Price alert poll unavailable')


def install(d):
    from flask import jsonify, request, redirect
    app = d.app
    if getattr(app, '_orca_watchlist_alerts', False):
        return
    app._orca_watchlist_alerts = True
    initialize(d.DB_FILE)
    def owner():
        wallet = d._authenticated_wallet()
        if not wallet:
            return None
        with sqlite3.connect(d.DB_FILE, timeout=10) as c:
            return d._get_uid(c, wallet)

    @app.after_request
    def private_watchlist(response):
        if request.path.startswith(('/api/watchlist', '/api/price-alerts')):
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.route('/watchlist')
    def watchlist_page():
        return redirect('/')

    @app.route('/api/price-alerts', methods=['GET', 'POST'])
    @d.rate_limit(60, 60)
    def price_alerts():
        uid = owner()
        if not uid:
            return jsonify(ok=False, msg='Connect your wallet first'), 401
        if request.method == 'GET':
            return jsonify(ok=True, alerts=alert_list(d.DB_FILE, uid))
        if not d._validate_csrf(request.headers.get('X-CSRF-Token', '')):
            return jsonify(ok=False, msg='Refresh the page and try again'), 403
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(ok=False, msg='Invalid alert'), 400
        mint = body.get('mint')
        if not isinstance(mint, str) or not d.is_valid_solana_address(mint):
            return jsonify(ok=False, msg='Enter a valid Solana token address'), 400
        try:
            aid = create_alert(d.DB_FILE, uid, mint, body.get('direction'), body.get('target'))
        except ValueError as e:
            return jsonify(ok=False, msg=str(e)), 400
        return jsonify(ok=True, id=aid)

    @app.route('/api/price-alerts/<int:aid>', methods=['DELETE'])
    @d.rate_limit(60, 60)
    def delete_price_alert(aid):
        uid = owner()
        if not uid:
            return jsonify(ok=False, msg='Connect your wallet first'), 401
        if not d._validate_csrf(request.headers.get('X-CSRF-Token', '')):
            return jsonify(ok=False, msg='Refresh the page and try again'), 403
        with sqlite3.connect(d.DB_FILE, timeout=10) as c:
            count = c.execute('DELETE FROM watch_price_alerts WHERE id=? AND user_id=?', (aid, uid)).rowcount
        return jsonify(ok=bool(count)), 200 if count else 404

    @d.rate_limit(60, 60)
    def bounded_watch_add(token_address):
        uid = owner()
        if not uid:
            return jsonify(ok=False, msg='Connect your wallet first'), 401
        if not d._validate_csrf(request.headers.get('X-CSRF-Token', '')):
            return jsonify(ok=False, msg='Refresh the page and try again'), 403
        if not d.is_valid_solana_address(token_address):
            return jsonify(ok=False, msg='Invalid Solana token address'), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(ok=False, msg='Invalid token'), 400
        symbol = str(body.get('symbol') or '').strip()[:20]
        with sqlite3.connect(d.DB_FILE, timeout=10) as c:
            c.execute('BEGIN IMMEDIATE')
            count = c.execute('SELECT COUNT(*) FROM watchlist WHERE user_id=?', (uid,)).fetchone()[0]
            exists = c.execute('SELECT 1 FROM watchlist WHERE user_id=? AND token_address=?', (uid, token_address)).fetchone()
            if count >= MAX_WATCHED and not exists:
                return jsonify(ok=False, msg='Your watchlist can hold up to 100 tokens'), 400
            c.execute('INSERT OR IGNORE INTO watchlist(user_id,token_address,symbol) VALUES(?,?,?)', (uid, token_address, symbol))
        return jsonify(ok=True)
    app.view_functions['api_watchlist_add'] = bounded_watch_add
    original_remove = app.view_functions['api_watchlist_remove']
    def remove_and_cancel(token_address):
        uid = owner()
        if uid and not d._validate_csrf(request.headers.get('X-CSRF-Token', '')):
            return jsonify(ok=False, msg='Refresh the page and try again'), 403
        result = original_remove(token_address)
        response = app.make_response(result)
        if uid and response.status_code == 200:
            with sqlite3.connect(d.DB_FILE, timeout=10) as c:
                c.execute('DELETE FROM watch_price_alerts WHERE user_id=? AND mint=?', (uid, token_address))
        return result
    app.view_functions['api_watchlist_remove'] = remove_and_cancel

    def run():
        while True:
            try:
                poll(d)
            except Exception:
                app.logger.warning('Price alert monitor unavailable')
            time.sleep(POLL_SECONDS)
    if os.getenv('ORCAGENT_PRICE_ALERTS', '1') == '1':
        threading.Thread(target=run, name='orca-price-alerts', daemon=True).start()
