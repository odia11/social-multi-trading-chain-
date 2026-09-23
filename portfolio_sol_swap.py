"""Portfolio USDC -> native SOL with funded and gasless execution paths.

A wallet that already has enough SOL uses the normal Jupiter swap path. Only a
wallet below the network-fee reserve requires a genuinely gasless Jupiter Ultra
order. Reviewed gasless orders are persisted across workers and consumed once.
"""
import json
import secrets
import sqlite3
import time
from decimal import Decimal, ROUND_DOWN

import requests
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


# Fallback when Jupiter's order omits its fee breakdown: two signatures,
# priority fee and a temporary wrapped-SOL account's rent, rounded up.
_FALLBACK_TAKER_FEE_SOL = Decimal('0.0025')


def taker_fee_sol(order):
    """SOL the taker itself must hold to land this Ultra order."""
    lamports = 0
    for field in ('signatureFeeLamports', 'prioritizationFeeLamports', 'rentFeeLamports'):
        payer = order.get(field[:-len('Lamports')] + 'Payer')
        if payer and payer != order.get('taker'):
            continue
        try:
            lamports += max(0, int(order.get(field) or 0))
        except (TypeError, ValueError):
            return _FALLBACK_TAKER_FEE_SOL
    if lamports <= 0:
        return _FALLBACK_TAKER_FEE_SOL
    return Decimal(lamports) / Decimal(1_000_000_000)


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
            sol, usdc = balances(wallet)
            if amount > usdc:
                return fail('Amount exceeds your Solana USDC balance')

            reserve = Decimal(str(d.SOL_NETWORK_RESERVE))
            if sol >= reserve:
                # Funded wallet: use the normal Jupiter quote/execution path.
                # Returning no quote_id intentionally makes the UI submit to
                # /api/wallet/convert, which signs the ordinary swap with the
                # user's own SOL paying network fees.
                jup_url = ((d.JUPITER_PROXY + '/quote') if d.JUPITER_PROXY
                           else 'https://api.jup.ag/swap/v1/quote')
                headers = {'Accept': 'application/json',
                           'User-Agent': 'Mozilla/5.0 OrcAgent/1.0'}
                if d.PROXY_SECRET:
                    headers['X-Proxy-Secret'] = d.PROXY_SECRET
                response = requests.get(jup_url, params={
                    'inputMint': d.USDC_MINT,
                    'outputMint': d.SOL_MINT,
                    'amount': int(amount * 1000000),
                    'slippageBps': 300,
                }, headers=headers, timeout=10)
                if response.status_code != 200:
                    return fail(f'Quote unavailable (HTTP {response.status_code})', 502)
                quote = response.json()
                out_raw = int(quote.get('outAmount', 0) or 0)
                min_raw = int(quote.get('otherAmountThreshold', 0) or 0)
                if out_raw <= 0:
                    return fail('No route found', 502)
                return jsonify(ok=True, chain='solana', direction='stable_to_native',
                               from_symbol='USDC', to_symbol='SOL',
                               out_amount=out_raw / 1e9,
                               min_out_amount=(min_raw / 1e9) if min_raw > 0 else 0,
                               price_impact_pct=float(quote.get('priceImpactPct') or 0),
                               network_reserve_native=float(reserve), gasless=False)

            # Low-SOL wallet: prefer a gasless Jupiter Ultra order. Jupiter only
            # offers gasless when the wallet cannot pay the fees itself, so a
            # wallet holding a few thousand lamports gets an ordinary Ultra
            # order instead. Take that one when this wallet can cover its
            # stated fees, rather than failing with "no gasless route".
            # No key is sent to Jupiter: only its derived public address.
            with d._use_key(key_blob(wallet), wallet) as key:
                order, output = provider._gasless_order(key, amount, require_gasless=False)
            gasless = bool(order.get('gasless'))
            fee_sol = Decimal(0) if gasless else taker_fee_sol(order)
            if not gasless and sol < fee_sol:
                return fail(f'Jupiter has no gasless route for this swap right now, and it needs about '
                            f'{fee_sol:.6f} SOL for network fees (this wallet holds {sol:.6f} SOL). '
                            'Add a little SOL to your trading wallet or try again later.', 400)
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
                           network_reserve_native=float(fee_sol), gasless=gasless)
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
                           amount_in=amount, gasless=bool(order.get('gasless')))
        except PermissionError as exc:
            return fail(exc, 401)
        except Exception as exc:
            return fail('Swap not confirmed. Check activity before retrying. ' + str(exc), 502)
