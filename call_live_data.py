"""Fresh, bounded public call quotes. Entry is immutable; peaks survive refreshes."""
import math
import sqlite3
import threading
import time
from flask import jsonify, request


def positive(value):
    try:
        value = float(value or 0)
        return value if math.isfinite(value) and value > 0 else 0
    except (ValueError, TypeError):
        return 0


def select_quote(pairs, mint):
    # Solana addresses are case-sensitive; quote-token pools price another asset.
    pairs = [p for p in pairs if p.get('chainId') == 'solana'
             and (p.get('baseToken') or {}).get('address') == mint
             and positive(p.get('priceUsd'))]
    if not pairs:
        return None
    p = max(pairs, key=lambda p: positive((p.get('liquidity') or {}).get('usd')))
    return {'price': positive(p.get('priceUsd')),
            'mcap': positive(p.get('marketCap')) or positive(p.get('fdv'))}


def record_quote(conn, mint, quote, observed_at):
    price, mcap = quote['price'], quote['mcap']
    conn.execute('''UPDATE token_calls SET
        peak_at=CASE WHEN ? > COALESCE(peak_price,price_at_call) THEN CURRENT_TIMESTAMP ELSE peak_at END,
        peak_price=MAX(COALESCE(peak_price,price_at_call),price_at_call,?),
        last_price=?, live_mcap=?,
        live_peak_mcap=MAX(COALESCE(live_peak_mcap,mcap_at_call,0),COALESCE(mcap_at_call,0),?),
        quote_at=?
        WHERE mint=? AND COALESCE(chain,'solana') IN ('','solana') AND COALESCE(quote_at,0) <= ?
        AND timestamp <= datetime(?,'unixepoch')''',
        (price, price, price, mcap or None, mcap, observed_at, mint, observed_at, observed_at))


def install(d):
    app = d.app
    lock = threading.Lock()
    last_attempt = {}
    # Migration runs before requests; pre-existing entry values are never modified.
    with sqlite3.connect(d.DB_FILE) as conn:
        for column in ('live_mcap REAL', 'live_peak_mcap REAL', 'quote_at REAL'):
            try:
                conn.execute('ALTER TABLE token_calls ADD COLUMN ' + column)
            except sqlite3.OperationalError as e:
                if 'duplicate column' not in str(e).lower():
                    raise

    @app.get('/api/calls/live')
    @d.rate_limit(30, 60)
    def live_calls():
        raw = request.args.get('ids', '').split(',')
        if len(raw) > 30 or not raw or any(not x.isdigit() for x in raw):
            return jsonify(ok=False, msg='Provide 1 to 30 call IDs'), 400
        ids = list(dict.fromkeys(int(x) for x in raw))
        ph = ','.join('?' for _ in ids)
        with lock:
            with sqlite3.connect(d.DB_FILE) as conn:
                rows = conn.execute('SELECT DISTINCT mint,quote_at FROM token_calls WHERE id IN (' + ph + ") AND COALESCE(chain,'') IN ('','solana')", ids).fetchall()
            mints = sorted({m for m, at in rows if time.time() - max(at or 0, last_attempt.get(m, 0)) >= 5 and d.is_valid_solana_address(m)})
            if mints:
                observed_at = time.time()
                for mint in mints:
                    last_attempt[mint] = observed_at
                if len(last_attempt) > 1000:
                    for mint in list(last_attempt):
                        if observed_at - last_attempt[mint] > 60:
                            last_attempt.pop(mint, None)
                try:
                    # No _dex_get: its rate-limit fallback returns old quotes without a timestamp.
                    r = d.requests.get('https://api.dexscreener.com/latest/dex/tokens/' + ','.join(mints),
                                       headers=d._DEX_HEADERS, timeout=8)
                    pairs = (r.json().get('pairs') or []) if r.status_code == 200 else []
                    with sqlite3.connect(d.DB_FILE) as conn:
                        for mint in mints:
                            quote = select_quote(pairs, mint)
                            if quote:
                                record_quote(conn, mint, quote, observed_at)
                except (d.requests.RequestException, ValueError, TypeError, AttributeError):
                    pass  # Preserve the last observation, and label it stale below.
            with sqlite3.connect(d.DB_FILE) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute('SELECT * FROM token_calls WHERE id IN (' + ph + ") AND COALESCE(chain,'') IN ('','solana')", ids).fetchall()
            calls = []
            for row in rows:
                c = dict(row)
                entry = positive(c['price_at_call'])
                peak = max(entry, positive(c['peak_price']))
                now = positive(c['last_price'])
                calls.append(dict(id=c['id'], mint=c['mint'], price_at_call=entry,
                    mcap_at_call=c['mcap_at_call'], last_price=now, peak_price=peak,
                    mcap_now=c['live_mcap'], mcap_peak=c['live_peak_mcap'],
                    multiplier=round(peak / entry, 4) if entry else 0,
                    now_multiplier=round(now / entry, 4) if entry else 0,
                    quote_at=c['quote_at'], stale=time.time() - (c['quote_at'] or 0) > 30))
        response = jsonify(ok=True, calls=calls)
        response.headers['Cache-Control'] = 'no-store'
        return response
