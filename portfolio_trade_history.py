"""Portfolio transaction history for Live Market BUY/SELL activity.

Adds one read-only endpoint and injects the matching Portfolio UI script.
The endpoint merges Trading Engine BUY executions with closed SELL rows so
users can inspect their actual OrcAgent trading activity by date.
"""
from __future__ import annotations

import datetime as _dt
import sqlite3


def _f(value, default=0.0):
    try:
        return float(value if value not in (None, '') else default)
    except Exception:
        return float(default)


def install(d):
    if getattr(d, '_orca_portfolio_trade_history_installed', False):
        return
    d._orca_portfolio_trade_history_installed = True
    app = d.app

    @app.route('/api/portfolio/transactions', methods=['GET'])
    def _portfolio_transactions():
        wallet = d._authenticated_wallet()
        if not wallet:
            return d.jsonify({'ok': False, 'msg': 'No wallet connected'}), 401

        side = str(d.request.args.get('side') or 'all').strip().lower()
        if side not in {'all', 'buy', 'sell'}:
            side = 'all'
        date_filter = str(d.request.args.get('date') or '').strip()
        if date_filter:
            try:
                _dt.date.fromisoformat(date_filter)
            except ValueError:
                return d.jsonify({'ok': False, 'msg': 'Invalid date'}), 400
        try:
            limit = max(1, min(250, int(d.request.args.get('limit') or 100)))
        except Exception:
            limit = 100

        conn = sqlite3.connect(d.DB_FILE)
        conn.row_factory = sqlite3.Row
        items = []
        try:
            uid = d._get_uid(conn, wallet)
            if not uid:
                return d.jsonify({'ok': True, 'transactions': [], 'count': 0})

            # BUYs: the central execution ledger records a transaction only once
            # it is actually completed. Join the quote to retain token + chain.
            if side in {'all', 'buy'}:
                try:
                    rows = conn.execute('''
                        SELECT e.trade_id, e.created_at, e.updated_at,
                               e.actual_spend_usd, e.max_spend_usd,
                               e.source_tx_hash, e.bridge_tx_hash,
                               e.destination_tx_hash, e.state,
                               q.destination_chain, q.token_address,
                               q.token_purchase_usd, q.mode
                        FROM trade_executions e
                        JOIN trade_quotes q ON q.quote_id=e.quote_id
                        WHERE e.user_id=? AND e.state='COMPLETED'
                        ORDER BY e.created_at DESC LIMIT ?
                    ''', (uid, limit)).fetchall()
                    for r in rows:
                        ts = _f(r['updated_at'] or r['created_at'])
                        spend = _f(r['actual_spend_usd'] or r['max_spend_usd'])
                        token_amount_usd = _f(r['token_purchase_usd'])
                        tx_hash = (r['destination_tx_hash'] or r['source_tx_hash'] or '').strip()
                        items.append({
                            'id': 'buy:' + str(r['trade_id']),
                            'side': 'buy',
                            'timestamp': ts,
                            'token': str(r['token_address'] or ''),
                            'symbol': '',
                            'chain': str(r['destination_chain'] or 'solana').lower(),
                            'amount_usd': spend,
                            'token_value_usd': token_amount_usd,
                            'price_usd': 0.0,
                            'pnl': None,
                            'pnl_pct': None,
                            'tx_hash': tx_hash,
                            'source': str(r['mode'] or 'manual'),
                        })
                except sqlite3.Error:
                    # Older DBs can briefly exist during a rolling deploy before
                    # trade-engine tables are present. SELL history still works.
                    pass

            # SELLs: a row is written to trades when a position is closed. This
            # is the authoritative realized sell record and includes PnL.
            if side in {'all', 'sell'}:
                rows = conn.execute('''
                    SELECT id, token, entry_price, exit_price, amount, pnl,
                           timestamp, mint_address, source, chain
                    FROM trades
                    WHERE user_id=? AND exit_price IS NOT NULL AND exit_price!=0
                    ORDER BY timestamp DESC LIMIT ?
                ''', (uid, limit)).fetchall()
                for r in rows:
                    raw_ts = r['timestamp']
                    try:
                        ts = _dt.datetime.fromisoformat(str(raw_ts).replace('Z', '+00:00')).timestamp()
                    except Exception:
                        ts = 0.0
                    entry = _f(r['entry_price'])
                    exit_price = _f(r['exit_price'])
                    amount = _f(r['amount'])
                    pnl = _f(r['pnl'])
                    pnl_pct = ((exit_price - entry) / entry * 100.0) if entry > 0 else 0.0
                    items.append({
                        'id': 'sell:' + str(r['id']),
                        'side': 'sell',
                        'timestamp': ts,
                        'token': str(r['mint_address'] or ''),
                        'symbol': str(r['token'] or ''),
                        'chain': str(r['chain'] or 'solana').lower(),
                        'amount_usd': max(0.0, amount * exit_price),
                        'token_value_usd': max(0.0, amount * exit_price),
                        'price_usd': exit_price,
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'tx_hash': '',
                        'source': str(r['source'] or 'manual'),
                    })
        finally:
            conn.close()

        # Optional calendar-day filtering happens after normalising timestamps,
        # so callers get the same behaviour for legacy ISO timestamps and the
        # newer unix timestamps in the execution ledger.
        if date_filter:
            filtered = []
            for item in items:
                try:
                    day = _dt.datetime.fromtimestamp(float(item['timestamp'])).date().isoformat()
                except Exception:
                    day = ''
                if day == date_filter:
                    filtered.append(item)
            items = filtered

        items.sort(key=lambda x: float(x.get('timestamp') or 0), reverse=True)
        items = items[:limit]
        return d.jsonify({'ok': True, 'transactions': items, 'count': len(items)})

    marker = 'data-orca-portfolio-trade-history="1"'

    @app.after_request
    def _inject_portfolio_trade_history(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            if (d.request.path.rstrip('/') or '/') != '/wallet':
                return response
            html = response.get_data(as_text=True)
            if marker in html:
                return response
            version = getattr(d, '_APP_VERSION', '1')
            tag = '<script src="/static/portfolio-trade-history.js?v=%s-tx1" defer %s></script>' % (version, marker)
            html = html.replace('</body>', tag + '</body>', 1) if '</body>' in html else html + tag
            response.set_data(html)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.debug('portfolio trade history injection skipped: %s', exc)
        return response
