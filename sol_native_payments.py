"""Native SOL transfers. Amounts are maximum wallet outflow, including fees.

No automatic conversion and no platform-funded gas. Historical SPL assets keep
their original units and remain withdrawable through the token endpoint.
"""
from decimal import Decimal, InvalidOperation
import base64
import sqlite3
import re
from flask import jsonify, request

LAMPORTS = Decimal(1_000_000_000)


def lamports(value):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Enter a valid SOL amount')
    if not amount.is_finite() or amount <= 0 or amount * LAMPORTS != (amount * LAMPORTS).to_integral_value():
        raise ValueError('Enter a positive SOL amount with at most 9 decimal places')
    return int(amount * LAMPORTS)


def sol_usdc_cost_allowance(owner, read):
    """Shared quote/execution reserve for canonical USDC account rent and fees."""
    from solders.pubkey import Pubkey
    token = Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')
    mint = Pubkey.from_string('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v')
    ata, _ = Pubkey.find_program_address([bytes(Pubkey.from_string(owner)),bytes(token),bytes(mint)],
        Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'))
    account = read('getAccountInfo',[str(ata),{'encoding':'base64','commitment':'confirmed'}])
    if not isinstance(account, dict) or 'value' not in account:
        raise RuntimeError('Cannot verify USDC account rent; conversion not sent')
    info = account['value']
    # Capped priority/signature fees plus the spend guard's conservative second fee count.
    allowance = 220_000
    if info is None:
        value = read('getMinimumBalanceForRentExemption',[165])
        if not isinstance(value, int) or value <= 0:
            raise RuntimeError('Cannot verify USDC account rent; conversion not sent')
        allowance += value
    elif not isinstance(info, dict) or info.get('owner') != str(token):
        raise RuntimeError('Invalid USDC token account; conversion not sent')
    return allowance


def native_transfer(d, wallet, recipient, ceiling, request_id):
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.hash import Hash
    from solders.system_program import transfer, TransferParams
    from solders.message import Message, to_bytes_versioned
    from solders.transaction import Transaction
    import portfolio_token_withdraw as provider

    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', request_id):
        raise ValueError('Refresh the app to create a valid transfer request')
    budget = lamports(ceiling)
    with sqlite3.connect(d.DB_FILE, timeout=10) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS native_sol_transfers (
            wallet TEXT NOT NULL, request_id TEXT NOT NULL, recipient TEXT NOT NULL,
            budget INTEGER NOT NULL, net INTEGER NOT NULL, signature TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'submitted', PRIMARY KEY(wallet,request_id))""")
        previous = db.execute('SELECT recipient,budget,net,signature,state FROM native_sol_transfers WHERE wallet=? AND request_id=?', (wallet, request_id)).fetchone()
        if previous:
            if previous[0] != recipient or previous[1] != budget:
                raise ValueError('Transfer request already used for a different amount or recipient')
            if previous[4] == 'failed':
                raise ValueError('Previous request failed; review the error before starting a new transfer')
            return previous[3], previous[2] / 1e9
    if not d.is_valid_solana_address(recipient):
        raise ValueError('Invalid Solana recipient address')
    row = provider._wallet_keys(d, wallet)
    if not row or not row[0]:
        raise ValueError('Create or connect your Solana trading wallet first')
    with d._use_key(row[0], wallet) as private_key:
        key = Keypair.from_base58_string(private_key)
        owner = str(key.pubkey())
        if owner == recipient:
            raise ValueError('Sender and recipient must be different wallets')
        balance, rpc = provider._rpc_call_any(d, 'getBalance', [owner, {'commitment': 'confirmed'}])
        available = int(balance['value'])
        block, _ = provider._rpc_call_any(d, 'getLatestBlockhash', [{'commitment': 'confirmed'}], preferred_url=rpc)
        blockhash = Hash.from_string(block['value']['blockhash'])

        def message(amount):
            ix = transfer(TransferParams(from_pubkey=key.pubkey(), to_pubkey=Pubkey.from_string(recipient), lamports=amount))
            return Message.new_with_blockhash([ix], key.pubkey(), blockhash)

        draft = message(budget)
        fee, _ = provider._rpc_call_any(d, 'getFeeForMessage',
            [base64.b64encode(to_bytes_versioned(draft)).decode(), {'commitment': 'confirmed'}], preferred_url=rpc)
        if not isinstance(fee, dict) or not isinstance(fee.get('value'), int) or fee['value'] <= 0:
            raise ValueError('Cannot verify the Solana network fee; no transfer was sent')
        net = budget - fee['value']
        if net <= 0:
            raise ValueError('SOL amount must exceed the network fee')
        floor = max(provider._fee_payer_rent_lamports(d), int(getattr(d, 'SOL_NETWORK_RESERVE', 0.005)*1e9))
        if available < budget + floor:
            raise ValueError('Insufficient SOL: keep the wallet rent reserve in addition to the send budget')
        tx = Transaction([key], message(net), blockhash)
        encoded = base64.b64encode(bytes(tx)).decode()
        # Preflight checks recipient rent requirements too. Never retry by
        # creating a new signed transaction after an ambiguous submission.
        signature = str(tx.signatures[0])
        with sqlite3.connect(d.DB_FILE, timeout=10) as db:
            claimed = db.execute('INSERT OR IGNORE INTO native_sol_transfers (wallet,request_id,recipient,budget,net,signature) VALUES (?,?,?,?,?,?)',
                (wallet, request_id, recipient, budget, net, signature)).rowcount
            if not claimed:
                previous = db.execute('SELECT recipient,budget,net,signature,state FROM native_sol_transfers WHERE wallet=? AND request_id=?', (wallet, request_id)).fetchone()
                if previous[0] != recipient or previous[1] != budget or previous[4] == 'failed':
                    raise ValueError('Transfer request already used')
                return previous[3], previous[2] / 1e9
        try:
            submitted, _ = provider._rpc_call_any(d, 'sendTransaction',
                            [encoded, {'encoding': 'base64', 'skipPreflight': False, 'preflightCommitment': 'confirmed', 'maxRetries': 3}], preferred_url=rpc)
            if submitted and str(submitted) != signature:
                raise RuntimeError('RPC returned an unexpected transfer signature')
        except provider._SolanaPreflightError:
            with sqlite3.connect(d.DB_FILE) as db:
                db.execute("UPDATE native_sol_transfers SET state='failed' WHERE wallet=? AND request_id=?", (wallet, request_id))
            raise
        except Exception:
            # Ambiguous transport failure: reconcile the precomputed signature.
            # Reusing this request never creates or submits a second payment.
            pass
    return str(signature), float(Decimal(net) / LAMPORTS)


def install(d):
    import portfolio_token_withdraw as provider

    @d.app.get('/api/wallet/trading-balance')
    def trading_balance():
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify(ok=False, error='Authentication required'), 401
        try:
            address = d._get_trading_wallet_address(wallet)
            if not address:
                return jsonify(ok=True, currency='SOL', balance_sol=0, available_sol=0,
                               sol_price_usd=d._sol_price_usd or None)
            result, _ = provider._rpc_call_any(d, 'getBalance', [address, {'commitment': 'confirmed'}])
            balance = int(result['value']) / 1e9
            response = jsonify(ok=True, currency='SOL', balance_sol=balance,
                available_sol=max(0, balance-d.SOL_NETWORK_RESERVE),
                network_reserve_sol=d.SOL_NETWORK_RESERVE,
                minimum_buy_sol=d.SOLANA_MIN_SPEND_SOL,
                sol_price_usd=d._sol_price_usd or None)
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        except Exception:
            return jsonify(ok=False, error='SOL balance temporarily unavailable'), 503

    @d.rate_limit(10, 60)
    def withdraw_native():
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify(ok=False, error='Authentication required'), 401
        if callable(getattr(d, '_rate_ok', None)) and not d._rate_ok('withdraw_wallet:' + wallet, 3, 3600):
            return jsonify(ok=False, error='Withdrawal limit reached. Try again later.'), 429
        if not provider._csrf_ok(d):
            return jsonify(ok=False, error='CSRF validation failed'), 403
        body = request.get_json(silent=True) or {}
        # Explicit native field avoids reinterpreting a stale USDC request.
        amount = body.get('amount_sol')
        try:
            lamports(amount)
            with provider._lock_for(wallet, 'solana'):
                sig, sent = native_transfer(d, wallet, str(body.get('to_address') or body.get('to') or '').strip(), amount, body.get('request_id'))
            return jsonify(ok=True, signature=sig, tx_hash=sig,
                           currency='SOL', amount_sent=sent, max_spend_sol=amount,
                           status='submitted', fee_deducted=float(Decimal(str(amount))-Decimal(str(sent))))
        except provider._SolanaPreflightError as exc:
            return jsonify(ok=False, error=str(exc), reason_code=exc.reason_code, status='failed'), 400
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc)), 400
        except Exception:
            return jsonify(ok=False, error='Transfer confirmation unavailable. Check Activity before retrying.'), 502

    d.app.view_functions['api_withdraw'] = withdraw_native
    d.app.view_functions['wallet_send'] = withdraw_native
