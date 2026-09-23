"""Portfolio USDC -> native SOL: user-funded gasless orders, no sponsor.

Persist the reviewed order across workers; consume it atomically before signing.
An uncertain execution must never create a second transaction automatically.
"""
import json
import secrets
import sqlite3
import time
from decimal import Decimal, ROUND_DOWN

from flask import jsonify, request
import solana_source_bridge_gasless as provider


def amount6(value):
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise ValueError('Enter an amount greater than zero')
    rounded = amount.quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    if rounded != amount or rounded <= 0:
        raise ValueError('USDC supports at most 6 decimal places')
    return rounded


def install(d):
    app = d.app
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS portfolio_sol_swap_orders (
            id TEXT PRIMARY KEY, wallet TEXT NOT NULL, amount TEXT NOT NULL,
            order_json TEXT NOT NULL, expires REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
        )''')

    def fail(message, status=400):
        return jsonify(ok=False, msg=d._redact_keys(str(message))[:300]), status

    def identity():
        wallet = d._authenticated_wallet()
        if not wallet:
            raise PermissionError('Not authenticated')
        return wallet

    def balances(wallet):
        address = d._get_trading_wallet_address(wallet)
        if not address:
            raise ValueError('No Solana trading wallet configured')
        sol = Decimal(str(d._get_user_sol(address)))
        usdc = Decimal(str(d._get_solana_usdc_balance(address)))
        if not sol.is_finite() or not usdc.is_finite() or min(sol, usdc) < 0:
            raise ValueError('Balance unavailable; please retry')
        return sol, usdc

    def key_blob(wallet):
        with sqlite3.connect(d.DB_FILE) as conn:
            row = conn.execute('SELECT encrypted_private_key FROM users WHERE wallet_address=?', (wallet,)).fetchone()
        if not row or not row[0]:
            raise ValueError('No Solana trading wallet configured')
        return row[0]

    @app.route('/api/wallet/sol-swap/balance')
    @d.rate_limit(30, 60)
    def portfolio_sol_swap_balance():
        try:
            sol, usdc = balances(identity())
            reserve = Decimal(str(d.SOL_NETWORK_RESERVE))
            maximum = max(Decimal(0), sol - reserve).quantize(Decimal('0.000000001'), rounding=ROUND_DOWN)
            return jsonify(ok=True, sol=str(sol), usdc=str(usdc),
                           max_sol=str(maximum), max_usdc=str(usdc.quantize(Decimal('0.000001'), rounding=ROUND_DOWN)),
                           network_reserve_native=str(reserve))
        except PermissionError as exc:
            return fail(exc, 401)
        except Exception as exc:
            return fail(exc, 502)

    @app.route('/api/wallet/sol-swap/quote')
    @d.rate_limit(30, 60)
    def portfolio_sol_swap_quote():
        try:
            wallet = identity()
            amount = amount6(request.args.get('amount', '0'))
            _, usdc = balances(wallet)
            if amount > usdc:
                return fail('Amount exceeds your Solana USDC balance')
            # This helper insists on gasless=True even for a funded wallet.
            # No key is sent to Jupiter: only its derived public address.
            with d._use_key(key_blob(wallet), wallet) as key:
                order, output = provider._gasless_order(key, amount)
            if int(order.get('inAmount', 0)) != int(amount * 1000000):
                return fail('Provider returned a different input amount', 502)
            minimum = int(order.get('otherAmountThreshold') or 0)
            if minimum <= 0 or not order.get('requestId'):
                return fail('Provider returned an incomplete swap quote', 502)
            token = secrets.token_urlsafe(32)
            now = time.time()
            with sqlite3.connect(d.DB_FILE) as conn:
                conn.execute('DELETE FROM portfolio_sol_swap_orders WHERE expires < ?', (now - 86400,))
                conn.execute('INSERT INTO portfolio_sol_swap_orders (id,wallet,amount,order_json,expires) VALUES (?,?,?,?,?)',
                             (token, wallet, str(amount), json.dumps(order), now + 45))
            return jsonify(ok=True, quote_id=token, expires_in=45, chain='solana',
                           direction='stable_to_native', from_symbol='USDC', to_symbol='SOL',
                           out_amount=float(output), min_out_amount=minimum / 1e9,
                           price_impact_pct=float(order.get('priceImpactPct') or 0),
                           network_reserve_native=0, gasless=True)
        except PermissionError as exc:
            return fail(exc, 401)
        except Exception as exc:
            return fail(exc, 502)

    @app.route('/api/wallet/sol-swap/execute', methods=['POST'])
    @d.rate_limit(5, 60)
    def portfolio_sol_swap_execute():
        try:
            wallet = identity()
            if not d._validate_csrf(request.headers.get('X-CSRF-Token', '')):
                return fail('CSRF validation failed', 403)
            data = request.get_json(silent=True) or {}
            token = str(data.get('quote_id') or '')
            with sqlite3.connect(d.DB_FILE) as conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute('SELECT amount,order_json FROM portfolio_sol_swap_orders WHERE id=? AND wallet=? AND consumed=0 AND expires>?',
                                   (token, wallet, time.time())).fetchone()
                if not row:
                    return fail('Quote expired or already submitted. Check activity before requesting a new quote.', 409)
                conn.execute('UPDATE portfolio_sol_swap_orders SET consumed=1 WHERE id=?', (token,))
            amount, order_json = row
            _, usdc = balances(wallet)
            if Decimal(amount) > usdc:
                return fail('Balance changed. Request a new quote.')
            order = json.loads(order_json)
            with d._use_key(key_blob(wallet), wallet) as key:
                signature, result = provider._execute_order(key, order)
            # No fallible balance/token RPC after a successful transaction.
            return jsonify(ok=True, tx_hash=signature, from_symbol='USDC', to_symbol='SOL',
                           amount_in=amount, gasless=True)
        except PermissionError as exc:
            return fail(exc, 401)
        except Exception as exc:
            return fail('Swap not confirmed. Check activity before retrying. ' + str(exc), 502)
