"""Verified Live Trades display and serialized manual overrides of bot positions."""
import math
import sqlite3
import threading
import time
from flask import jsonify, request

def number(value):
    try:
        result = float(value or 0)
        return result if math.isfinite(result) else 0.0
    except (TypeError, ValueError):
        return 0.0

def normalize(position, base, sol_rate, held):
    p = dict(position)
    rate = number(sol_rate) if (base or 'SOL').upper() == 'SOL' else 1.0
    p['balance_verified'] = held is not None
    p['can_sell'] = held is not None and number(held) > 0
    amount = min(number(p.get('amount')), number(held)) if held is not None else 0
    p['amount'] = amount
    for key in ('entry_price', 'tp_price', 'sl_price'):
        p[key] = number(p.get(key)) * rate if rate > 0 else None
    entry = number(p.get('entry_price'))
    current = number(p.get('current_price'))
    known = bool(p.get('price_known')) and entry > 0 and rate > 0 and held is not None
    p['price_known'] = known
    p['stake_usd'] = entry * amount if held is not None and rate > 0 else None
    p['pnl_pct'] = round((current / entry - 1) * 100, 2) if known else None
    p['pnl_usd'] = round((current - entry) * amount, 2) if known else None
    return p

def install(d):
    if getattr(d, '_orca_live_trades_truth', False):
        return
    d._orca_live_trades_truth = True
    original = d._fetch_open_bot_positions
    cache, guard = {}, threading.Lock()

    def inventory(wallet, fresh=False):
        owner = d._get_trading_wallet_address(wallet) or wallet
        key = (wallet, owner)
        with guard:
            hit = cache.get(key)
            if not fresh and hit and time.monotonic() - hit[0] < 10:
                return owner, hit[1]
        # Ordinary account reads cover both SPL programs, validate mint and
        # owner bytes, and return balances only from the spending wallet's ATAs.
        rows = d._known_wallet_token_accounts(wallet, owner)
        balances = {r['mint']: number(r['amount']) for r in rows}
        with guard:
            cache[key] = (time.monotonic(), balances)
        return owner, balances

    def positions(wallet):
        raw = original(wallet)
        if not raw:
            return []
        with sqlite3.connect(d.DB_FILE) as c:
            rows = c.execute(
                "SELECT p.mint_address,p.base_currency FROM open_positions p "
                "JOIN users u ON u.id=p.user_id WHERE u.wallet_address=?", (wallet,)).fetchall()
        bases = dict(rows)
        try:
            _, balances = inventory(wallet)
        except Exception:
            balances = None
        out = []
        for p in raw:
            mint = p['mint_address']
            if balances is not None and balances.get(mint, 0) <= 0:
                continue  # stale administrative row is not an open holding
            held = balances.get(mint, 0) if balances is not None else None
            out.append(normalize(p, bases.get(mint, 'SOL'), d._sol_price_usd, held))
        return out

    d._fetch_open_bot_positions = positions

    def page():
        wallet = d._authenticated_wallet()
        if not wallet:
            return d.redirect('/')
        owner = d._get_trading_wallet_address(wallet) or wallet
        return d._render_no_cache('live_trades.html',
            open_positions=positions(wallet), closed_trades=d._fetch_closed_bot_trades(wallet),
            bot_status=d._bot_status_summary(wallet), wallet=wallet,
            wallet_short=wallet[:4] + '...' + wallet[-4:],
            trading_wallet=owner, csrf_token=d._get_csrf_token())
    d.app.view_functions['live_trades'] = page

    @d.app.route('/api/live-trades/sell', methods=['POST'])
    @d.rate_limit(10, 60)
    def sell():
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify(ok=False, msg='Connect your wallet first'), 401
        body = request.get_json(silent=True) or {}
        mint = str(body.get('mint_address') or '').strip()
        if not d.is_valid_solana_address(mint):
            return jsonify(ok=False, msg='Invalid token address'), 400
        if d._sec_check_state.get('trading_paused'):
            return jsonify(ok=False, msg='Trading is temporarily paused'), 503
        lock = d._get_sell_lock(wallet, mint, 'solana')
        if not lock.acquire(blocking=False):
            return jsonify(ok=False, msg='A sell is already in progress for this token'), 409
        try:
            with sqlite3.connect(d.DB_FILE) as c:
                row = c.execute('SELECT id,encrypted_private_key FROM users WHERE wallet_address=?',
                                (wallet,)).fetchone()
                owned = c.execute(
                    "SELECT 1 FROM open_positions WHERE user_id=? AND mint_address=? "
                    "AND source IN ('bot','narrative') AND COALESCE(chain,'solana')='solana'",
                    (row[0] if row else -1, mint)).fetchone()
            if not row or not row[1] or not owned:
                return jsonify(ok=False, msg='No bot position for your account'), 404
            us = d.get_user_state(wallet)
            pos = us.get('positions', {}).get(mint)
            if not pos or number(pos.get('amount')) <= 0:
                return jsonify(ok=False, msg='This position has already closed'), 409
            try:
                _, balances = inventory(wallet, fresh=True)
            except Exception:
                return jsonify(ok=False, msg='Could not verify your token balance. Try again shortly.'), 503
            held = balances.get(mint, 0)
            if held <= 0:
                return jsonify(ok=False, msg='Your trading wallet does not hold this token'), 409
            price = number((d.get_token_data(mint, fast=True) or {}).get('price'))
            # The existing execution/ledger helper expects price in the
            # position's historical base currency, unlike this dollar UI.
            if (pos.get('base') or 'SOL') == 'SOL':
                price = price / d._sol_price_usd if d._sol_price_usd > 0 else 0
            symbol = pos.get('symbol') or mint[:8]
            ok, _, _ = d._bot_execute_exit_locked(
                row[0], us, wallet, mint, pos, price, symbol, held,
                number(pos.get('spend')), 'MANUAL OVERRIDE', True,
                row[1], 'solana', True, {})
            if not ok:
                return jsonify(ok=False, msg='Sell failed. Your position remains open.'), 502
            # Close under the SAME lock as the swap so the auto bot cannot
            # enter a second exit before the successful close is recorded.
            d._close_open_position(row[0], wallet, mint)
            with guard:
                cache.clear()
            d._wallet_tokens_cache.pop(wallet, None)
            return jsonify(ok=True, msg='Sold ' + symbol, symbol=symbol)
        except Exception:
            d.app.logger.exception('Live Trades manual override failed')
            return jsonify(ok=False, msg='Could not complete the sell. Refresh before retrying.'), 500
        finally:
            lock.release()
