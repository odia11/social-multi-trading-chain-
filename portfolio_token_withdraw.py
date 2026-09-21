"""Withdraw any token shown in Portfolio to another wallet.

Supports Solana SPL/Token-2022 tokens and ERC-20 tokens on every EVM chain
OrcAgent already trades.  The server derives the source trading wallet from
the authenticated user, re-reads the token balance on-chain, validates the
recipient, serialises sends per wallet+chain, and never accepts a caller-
supplied sender/private key.
"""
from __future__ import annotations

import base64
import sqlite3
import threading
import time
from decimal import Decimal, InvalidOperation, ROUND_DOWN

import requests
from flask import jsonify, request

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_RECENT = {}
_RECENT_GUARD = threading.Lock()


def _lock_for(wallet: str, chain: str):
    key = (wallet, chain)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _amount(value):
    try:
        x = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return x if x.is_finite() and x > 0 else None


def _wallet_keys(d, wallet):
    conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
    try:
        return conn.execute(
            'SELECT encrypted_private_key, encrypted_private_key_bsc, bsc_wallet_address '
            'FROM users WHERE wallet_address=? LIMIT 1', (wallet,)
        ).fetchone()
    finally:
        conn.close()


def _csrf_ok(d):
    fn = getattr(d, '_validate_csrf', None)
    token = request.headers.get('X-CSRF-Token', '') or request.headers.get('X-CSRFToken', '')
    return bool(callable(fn) and fn(token))


def _rpc_urls(d):
    urls = []
    for url in (list(getattr(d, 'CLAIM_SOL_RPCS', []) or [])
                + [getattr(d, 'SOLANA_RPC', None), getattr(d, 'SOLANA_RPC_URL', None)]
                + list(getattr(d, '_PROXY_RPCS', []) or [])):
        url = str(url or '').strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _rpc(d):
    urls = _rpc_urls(d)
    return urls[0] if urls else ''


def _rpc_call(url, method, params):
    r = requests.post(url, json={'jsonrpc':'2.0','id':1,'method':method,'params':params}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError('Solana RPC HTTP %s' % r.status_code)
    body = r.json()
    if body.get('error'):
        raise RuntimeError(str(body['error'].get('message') or body['error']))
    if 'result' not in body:
        raise RuntimeError('Solana RPC response missing result')
    return body.get('result')


def _rpc_call_any(d, method, params, require_nonempty=False):
    """Read from the first healthy Solana RPC, returning (result, url).

    An empty token-account list is not considered authoritative while other
    configured providers remain, because OrcAgent has observed public RPCs
    return [] while a configured provider immediately returns the real SPL
    accounts.
    """
    last = None
    empty = None
    for url in _rpc_urls(d):
        try:
            result = _rpc_call(url, method, params)
            if require_nonempty:
                value = (result or {}).get('value') if isinstance(result, dict) else None
                if not value:
                    empty = (result, url)
                    continue
            return result, url
        except Exception as exc:
            last = exc
            continue
    if empty is not None:
        return empty
    if last:
        raise last
    raise RuntimeError('No Solana RPC is configured')


def _solana_transfer(d, wallet, token_address, to_address, amount):
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.transaction import Transaction

    urls = _rpc_urls(d)
    if not urls:
        raise RuntimeError('Solana network is unavailable')
    try:
        mint = Pubkey.from_string(token_address)
        recipient = Pubkey.from_string(to_address)
    except Exception:
        raise ValueError('Invalid Solana wallet or token address')

    owner_text = str(d._get_trading_wallet_address(wallet) or '')
    if not owner_text:
        raise RuntimeError('Solana trading wallet is not configured')
    if owner_text == to_address:
        raise ValueError('Destination is the same as your trading wallet')
    owner = Pubkey.from_string(owner_text)

    # The exact source token account and its decimals are server-read.
    result, url = _rpc_call_any(d, 'getTokenAccountsByOwner', [
        owner_text, {'mint': token_address}, {'encoding':'jsonParsed'}
    ], require_nonempty=True)
    result = result or {}
    accounts = result.get('value') or []
    source = None
    balance_raw = 0
    decimals = 0
    token_program = None
    for entry in accounts:
        try:
            info = entry['account']['data']['parsed']['info']
            ta = info['tokenAmount']
            raw = int(ta.get('amount') or 0)
            if raw > balance_raw:
                balance_raw = raw
                decimals = int(ta.get('decimals') or 0)
                source = Pubkey.from_string(entry['pubkey'])
                token_program = Pubkey.from_string(entry['account']['owner'])
        except Exception:
            continue
    if source is None or token_program is None or balance_raw <= 0:
        raise ValueError('This token is not available in your Solana trading wallet')

    scale = Decimal(10) ** decimals
    send_raw = int((amount * scale).to_integral_value(rounding=ROUND_DOWN))
    if send_raw <= 0:
        raise ValueError('Amount is too small')
    if send_raw > balance_raw:
        raise ValueError('Amount is higher than your on-chain token balance')

    # Associated token account is derived from the recipient wallet. Works for
    # both classic SPL Token and Token-2022 because the token program is part
    # of the ATA seed.
    ata_program = Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
    system_program = Pubkey.from_string('11111111111111111111111111111111')
    dest_ata, _ = Pubkey.find_program_address(
        [bytes(recipient), bytes(token_program), bytes(mint)], ata_program
    )

    instructions = []
    dest_info, _ = _rpc_call_any(d, 'getAccountInfo', [str(dest_ata), {'encoding':'base64'}])
    if not dest_info or not dest_info.get('value'):
        # CreateAssociatedTokenAccountIdempotent (instruction=1).
        instructions.append(Instruction(
            ata_program,
            bytes([1]),
            [AccountMeta(owner, True, True), AccountMeta(dest_ata, False, True),
             AccountMeta(recipient, False, False), AccountMeta(mint, False, False),
             AccountMeta(system_program, False, False), AccountMeta(token_program, False, False)]
        ))

    # SPL Token TransferChecked: enum index 12 + u64 amount + u8 decimals.
    data = bytes([12]) + int(send_raw).to_bytes(8, 'little') + bytes([decimals])
    instructions.append(Instruction(
        token_program, data,
        [AccountMeta(source, False, True), AccountMeta(mint, False, False),
         AccountMeta(dest_ata, False, True), AccountMeta(owner, True, False)]
    ))

    row = _wallet_keys(d, wallet)
    enc = str(row[0] or '').strip() if row else ''
    if not enc:
        raise RuntimeError('Solana trading key is not configured')

    # Require user-funded SOL for network/rent. OrcAgent never subsidises it.
    native, _ = _rpc_call_any(d, 'getBalance', [owner_text, {'commitment':'confirmed'}])
    lamports = int((native or {}).get('value') or 0)
    if lamports < 10000:
        raise ValueError('Not enough SOL in your trading wallet to pay the network fee')

    bh_result, _ = _rpc_call_any(d, 'getLatestBlockhash', [{'commitment':'confirmed'}])
    blockhash = (bh_result or {}).get('value', {}).get('blockhash')
    if not blockhash:
        raise RuntimeError('Could not get a recent Solana blockhash')

    with d._use_key(enc, wallet) as private_key:
        kp = Keypair.from_base58_string(private_key)
        if kp.pubkey() != owner:
            raise RuntimeError('Trading key does not match the source wallet')
        tx = Transaction.new_signed_with_payer(instructions, owner, [kp], Hash.from_string(blockhash))
        encoded = base64.b64encode(bytes(tx)).decode('ascii')

    sig, _ = _rpc_call_any(d, 'sendTransaction', [encoded, {
        'encoding':'base64', 'skipPreflight':False, 'preflightCommitment':'confirmed',
        'maxRetries':3
    }])
    return str(sig), float(Decimal(send_raw) / scale)


def _evm_transfer(d, wallet, chain, token_address, to_address, amount):
    from web3 import Web3

    if chain not in getattr(d, 'EVM_CHAINS', {}):
        raise ValueError('Unsupported network')
    if not Web3.is_address(to_address) or not Web3.is_address(token_address):
        raise ValueError('Invalid EVM wallet or token address')

    row = _wallet_keys(d, wallet)
    enc = str(row[1] or '').strip() if row else ''
    source_text = str(row[2] or '').strip() if row else ''
    if not enc or not source_text:
        raise RuntimeError('EVM trading wallet is not configured')
    if to_address.lower() == source_text.lower():
        raise ValueError('Destination is the same as your trading wallet')

    w3 = d._get_web3(chain)
    source = w3.to_checksum_address(source_text)
    dest = w3.to_checksum_address(to_address)
    token = w3.to_checksum_address(token_address)
    abi = [
        {'constant':True,'inputs':[{'name':'a','type':'address'}],'name':'balanceOf','outputs':[{'name':'','type':'uint256'}],'type':'function'},
        {'constant':True,'inputs':[],'name':'decimals','outputs':[{'name':'','type':'uint8'}],'type':'function'},
        {'constant':False,'inputs':[{'name':'to','type':'address'},{'name':'v','type':'uint256'}],'name':'transfer','outputs':[{'name':'','type':'bool'}],'type':'function'},
    ]
    contract = w3.eth.contract(address=token, abi=abi)
    decimals = int(contract.functions.decimals().call())
    raw_balance = int(contract.functions.balanceOf(source).call())
    scale = Decimal(10) ** decimals
    send_raw = int((amount * scale).to_integral_value(rounding=ROUND_DOWN))
    if send_raw <= 0:
        raise ValueError('Amount is too small')
    if send_raw > raw_balance:
        raise ValueError('Amount is higher than your on-chain token balance')

    fn = contract.functions.transfer(dest, send_raw)
    nonce = w3.eth.get_transaction_count(source, 'pending')
    gas = int(fn.estimate_gas({'from':source}) * 1.20)
    gas_price = int(w3.eth.gas_price)
    gas_needed = gas * gas_price
    if int(w3.eth.get_balance(source)) < gas_needed:
        sym = str(getattr(d, 'EVM_CHAINS', {}).get(chain, {}).get('native_symbol') or 'native gas token')
        raise ValueError('Not enough %s in your trading wallet to pay the network fee' % sym)

    tx = fn.build_transaction({
        'from': source, 'nonce': nonce, 'gas': gas, 'gasPrice': gas_price,
        'chainId': int(w3.eth.chain_id),
    })
    with d._use_key(enc, wallet) as private_key:
        signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
        raw = getattr(signed, 'raw_transaction', None) or getattr(signed, 'rawTransaction')
        tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
    if int(getattr(receipt, 'status', receipt.get('status', 0))) != 1:
        raise RuntimeError('Token transfer was reverted by the network')
    return tx_hash.hex(), float(Decimal(send_raw) / scale)


def _explorer(chain, tx_hash):
    bases = {
        'solana':'https://solscan.io/tx/', 'bsc':'https://bscscan.com/tx/',
        'base':'https://basescan.org/tx/', 'arbitrum':'https://arbiscan.io/tx/',
        'polygon':'https://polygonscan.com/tx/',
        'robinhood':'https://explorer.testnet.chain.robinhood.com/tx/',
    }
    base = bases.get(chain)
    return base + tx_hash if base and tx_hash else ''


def _user_tip_wallets(d, user_id):
    conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
    try:
        row = conn.execute(
            'SELECT wallet_address, COALESCE(bsc_wallet_address, "") FROM users WHERE id=?',
            (int(user_id),)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    session_wallet, evm_wallet = str(row[0] or ''), str(row[1] or '')
    try:
        solana_wallet = str(d._get_trading_wallet_address(session_wallet) or session_wallet)
    except Exception:
        solana_wallet = session_wallet
    return {'session': session_wallet, 'solana': solana_wallet, 'evm': evm_wallet}


def _tip_solana_ready(d, sender_wallet, amount):
    try:
        owner = str(d._get_trading_wallet_address(sender_wallet) or '')
        if not owner:
            return None
    except Exception:
        return None

    balance = Decimal('0')
    try:
        balance = Decimal(str(d._get_solana_usdc_balance(owner)))
    except Exception:
        pass

    # A too-low result is reconciled against the broader SPL scanner as well,
    # not only on exceptions. This protects against stale/empty mint-filtered
    # RPC responses without trusting client-supplied balances.
    if balance < amount:
        try:
            try:
                d._wallet_tokens_cache.pop(sender_wallet, None)
            except Exception:
                pass
            data = d._fetch_wallet_tokens(sender_wallet, owner) or {}
            scanned = Decimal('0')
            for token in data.get('tokens') or []:
                if str(token.get('mint') or '') == str(d.USDC_MINT):
                    scanned += Decimal(str(token.get('amount') or 0))
            if scanned > balance:
                balance = scanned
        except Exception:
            pass

    if balance < amount:
        return None

    lamports = 0
    try:
        native, _ = _rpc_call_any(
            d, 'getBalance', [owner, {'commitment':'confirmed'}])
        lamports = int((native or {}).get('value') or 0)
    except Exception:
        lamports = 0

    return {
        'chain':'solana', 'balance':balance,
        'native_ready': lamports >= 10000,
        'lamports': lamports,
    }


def _tip_evm_candidates(d, sender_wallet, amount, recipient_evm):
    if not recipient_evm:
        return [], []
    row = _wallet_keys(d, sender_wallet)
    source = str(row[2] or '').strip() if row else ''
    if not source:
        return [], []
    ready, needs_gas = [], []
    for chain, cfg in getattr(d, 'EVM_CHAINS', {}).items():
        # A USDC tip must arrive as USDC. Robinhood currently uses USDG as
        # its trading stablecoin, so it is deliberately not a tip rail until
        # native USDC is configured there.
        if str(cfg.get('usdc_symbol') or 'USDC').upper() != 'USDC':
            continue
        try:
            balance = Decimal(str(d.get_evm_usdc_balance(source, chain)))
            if balance < amount:
                continue
            native = Decimal(str(d.get_evm_native_balance(source, chain)))
            item = {'chain':chain, 'balance':balance,
                    'token':str(cfg.get('usdc') or ''), 'source':source}
            (ready if native > 0 else needs_gas).append(item)
        except Exception:
            continue
    ready.sort(key=lambda x: x['balance'], reverse=True)
    needs_gas.sort(key=lambda x: x['balance'], reverse=True)
    return ready, needs_gas


def _record_tip(d, sender_wallet, sender_user_id, recipient_user_id,
                recipient_wallet, amount, chain, tx_hash):
    conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS tip_transactions ('
                     'id INTEGER PRIMARY KEY AUTOINCREMENT,'
                     'sender_user_id INTEGER NOT NULL,'
                     'recipient_user_id INTEGER NOT NULL,'
                     'sender_wallet TEXT NOT NULL,'
                     'recipient_wallet TEXT NOT NULL,'
                     'amount REAL NOT NULL,'
                     'chain TEXT NOT NULL,'
                     'tx_hash TEXT NOT NULL,'
                     "status TEXT NOT NULL DEFAULT 'confirmed',"
                     'created_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tips_sender ON tip_transactions(sender_user_id, created_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tips_recipient ON tip_transactions(recipient_user_id, created_at)')
        conn.execute(
            'INSERT INTO tip_transactions '
            '(sender_user_id,recipient_user_id,sender_wallet,recipient_wallet,amount,chain,tx_hash,status) '
            'VALUES (?,?,?,?,?,?,?,?)',
            (sender_user_id, recipient_user_id, sender_wallet, recipient_wallet,
             float(amount), chain, tx_hash, 'confirmed'))
        conn.execute(
            'INSERT INTO notifications (user_id,type,content,link,actor_wallet) VALUES (?,?,?,?,?)',
            (recipient_user_id, 'tip', 'You received %.2f USDC tip.' % float(amount),
             '/wallet', sender_wallet))
        conn.commit()
    finally:
        conn.close()


def install(d):
    app = d.app
    if getattr(app, '_orca_portfolio_token_withdraw_installed', False):
        return
    app._orca_portfolio_token_withdraw_installed = True

    @app.post('/api/tip')
    def _send_user_tip():
        sender_wallet = d._authenticated_wallet()
        if not sender_wallet:
            return jsonify({'ok':False,'error':'Authentication required'}), 401
        if not _csrf_ok(d):
            return jsonify({'ok':False,'error':'CSRF validation failed'}), 403
        if callable(getattr(d, '_rate_ok', None)) and not d._rate_ok('tip_wallet:' + sender_wallet, 12, 3600):
            return jsonify({'ok':False,'error':'Tip limit reached. Try again later.'}), 429

        body = request.get_json(silent=True) or {}
        try:
            recipient_user_id = int(body.get('recipient_user_id'))
        except (TypeError, ValueError):
            return jsonify({'ok':False,'error':'Invalid recipient'}), 400
        amount = _amount(body.get('amount'))
        if amount is None:
            return jsonify({'ok':False,'error':'Enter a positive USDC amount'}), 400
        if amount > Decimal('10000'):
            return jsonify({'ok':False,'error':'Tip amount is above the per-transfer limit'}), 400

        conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
        try:
            sender_row = conn.execute(
                'SELECT id FROM users WHERE wallet_address=? LIMIT 1',
                (sender_wallet,)).fetchone()
        finally:
            conn.close()
        if not sender_row:
            return jsonify({'ok':False,'error':'Sender account not found'}), 404
        sender_user_id = int(sender_row[0])
        if sender_user_id == recipient_user_id:
            return jsonify({'ok':False,'error':'You cannot tip yourself'}), 400

        recipient = _user_tip_wallets(d, recipient_user_id)
        if not recipient:
            return jsonify({'ok':False,'error':'Recipient account not found'}), 404

        key = ('tip', sender_wallet, recipient_user_id, str(amount.normalize()))
        now = time.time()
        with _RECENT_GUARD:
            if now - _RECENT.get(key, 0) < 45:
                return jsonify({'ok':False,'error':'This tip was already submitted recently'}), 409

        lock = _lock_for(sender_wallet, 'tip')
        if not lock.acquire(blocking=False):
            return jsonify({'ok':False,'error':'Another tip is already in progress'}), 409
        try:
            ready_evm, gasless_evm = _tip_evm_candidates(
                d, sender_wallet, amount, recipient.get('evm'))
            sol = _tip_solana_ready(d, sender_wallet, amount)

            candidates = list(ready_evm)
            if sol and sol.get('native_ready'):
                candidates.append(sol)
            candidates.sort(key=lambda x: x['balance'], reverse=True)

            tx_hash = ''
            sent = 0.0
            chain = ''
            recipient_address = ''

            for candidate in candidates:
                chain = candidate['chain']
                try:
                    if chain == 'solana':
                        recipient_address = recipient['solana']
                        tx_hash, sent = _solana_transfer(
                            d, sender_wallet, d.USDC_MINT,
                            recipient_address, amount)
                    else:
                        recipient_address = recipient['evm']
                        tx_hash, sent = _evm_transfer(
                            d, sender_wallet, chain, candidate['token'],
                            recipient_address, amount)
                    break
                except Exception:
                    tx_hash = ''

            if not tx_hash and sol and not sol.get('native_ready'):
                spare = sol['balance'] - amount
                topup = getattr(d, '_gasless_solana_native_topup', None)
                if callable(topup) and spare >= Decimal('0.20'):
                    try:
                        topup(sender_wallet, spare, target_sol=0.0025)
                        recipient_address = recipient['solana']
                        chain = 'solana'
                        tx_hash, sent = _solana_transfer(
                            d, sender_wallet, d.USDC_MINT,
                            recipient_address, amount)
                    except Exception as exc:
                        app.logger.info(
                            'solana tip gas bootstrap unavailable wallet=%s error=%s',
                            sender_wallet[:8] + '…', type(exc).__name__)
                        tx_hash = ''

            if not tx_hash:
                topup_amount = Decimal(str(getattr(d, 'GAS_TOPUP_USDC_AMOUNT', 2.0)))
                for candidate in gasless_evm:
                    if candidate['balance'] < amount + topup_amount:
                        continue
                    chain = candidate['chain']
                    try:
                        row = _wallet_keys(d, sender_wallet)
                        enc = str(row[1] or '').strip() if row else ''
                        topup = getattr(d, '_gasless_evm_native_topup', None)
                        if not enc or not callable(topup):
                            continue
                        with d._use_key(enc, sender_wallet) as private_key:
                            topup(private_key, chain)
                        recipient_address = recipient['evm']
                        tx_hash, sent = _evm_transfer(
                            d, sender_wallet, chain, candidate['token'],
                            recipient_address, amount)
                        break
                    except Exception:
                        tx_hash = ''

            if not tx_hash:
                return jsonify({
                    'ok':False,
                    'error':'This tip cannot be sent yet. There is enough USDC only if the wallet can also create or pay its network gas.'
                }), 400

            with _RECENT_GUARD:
                _RECENT[key] = time.time()
            _record_tip(d, sender_wallet, sender_user_id, recipient_user_id,
                        recipient_address, amount, chain, tx_hash)
            try:
                d._wallet_tokens_cache.pop(sender_wallet, None)
                d._wallet_tokens_cache.pop(recipient['session'], None)
            except Exception:
                pass
            try:
                d.add_user_log(sender_wallet,
                    'TIP: %.2f USDC sent to user %s · tx %s' %
                    (float(amount), recipient_user_id, tx_hash[:12]))
            except Exception:
                pass
            return jsonify({
                'ok':True, 'amount_sent':sent, 'currency':'USDC',
                'chain':chain, 'tx_hash':tx_hash,
                'explorer':_explorer(chain, tx_hash)
            })
        except Exception as exc:
            app.logger.warning('user tip failed wallet=%s error=%s',
                               sender_wallet[:8] + '…', type(exc).__name__)
            return jsonify({'ok':False,'error':'Tip transfer failed. Please try again after checking your balance.'}), 502
        finally:
            lock.release()

    @app.post('/api/wallet/send-token')
    def _send_portfolio_token():
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify({'ok':False,'error':'Authentication required'}), 401
        if not _csrf_ok(d):
            return jsonify({'ok':False,'error':'CSRF validation failed'}), 403
        if callable(getattr(d, '_rate_ok', None)) and not d._rate_ok('withdraw_wallet:' + wallet, 3, 3600):
            return jsonify({'ok':False,'error':'Withdrawal limit reached. Try again later.'}), 429

        body = request.get_json(silent=True) or {}
        chain = str(body.get('chain') or '').strip().lower()
        token_address = str(body.get('token_address') or '').strip()
        to_address = str(body.get('to_address') or '').strip()
        amount = _amount(body.get('amount'))
        if chain != 'solana' and chain not in getattr(d, 'EVM_CHAINS', {}):
            return jsonify({'ok':False,'error':'Unsupported network'}), 400
        if not token_address or not to_address or amount is None:
            return jsonify({'ok':False,'error':'Token, recipient and a positive amount are required'}), 400

        key = (wallet, chain, token_address.lower(), to_address.lower(), str(amount.normalize()))
        now = time.time()
        with _RECENT_GUARD:
            last = _RECENT.get(key, 0)
            if now - last < 45:
                return jsonify({'ok':False,'error':'This token transfer was already submitted recently'}), 409

        lock = _lock_for(wallet, chain)
        if not lock.acquire(blocking=False):
            return jsonify({'ok':False,'error':'Another withdrawal is already in progress'}), 409
        try:
            if chain == 'solana':
                tx_hash, sent = _solana_transfer(d, wallet, token_address, to_address, amount)
            else:
                tx_hash, sent = _evm_transfer(d, wallet, chain, token_address, to_address, amount)
            with _RECENT_GUARD:
                _RECENT[key] = time.time()
            try:
                d._wallet_tokens_cache.pop(wallet, None)
            except Exception:
                pass
            try:
                d.add_user_log(wallet, 'WITHDRAW TOKEN: %.8g sent on %s · tx %s' % (sent, chain, tx_hash[:12]))
            except Exception:
                pass
            return jsonify({
                'ok':True, 'chain':chain, 'token_address':token_address,
                'amount_sent':sent, 'tx_hash':tx_hash, 'explorer':_explorer(chain, tx_hash)
            })
        except ValueError as exc:
            return jsonify({'ok':False,'error':str(exc)}), 400
        except Exception as exc:
            app.logger.warning('portfolio token withdrawal failed chain=%s wallet=%s error=%s',
                               chain, wallet[:8] + '…', type(exc).__name__)
            return jsonify({'ok':False,'error':'Token transfer failed. Check the recipient, balance and network fee, then try again.'}), 502
        finally:
            lock.release()

    marker = 'data-orca-token-withdraw="1"'
    @app.after_request
    def _inject_token_withdraw_ui(response):
        try:
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            if (request.path.rstrip('/') or '/') != '/wallet':
                return response
            html = response.get_data(as_text=True)
            if marker in html:
                return response
            tag = '<script src="/static/portfolio-token-send.js?v=1" defer %s></script>' % marker
            html = html.replace('</body>', tag + '</body>', 1) if '</body>' in html else html + tag
            response.set_data(html)
            response.content_length = len(response.get_data())
        except Exception:
            app.logger.exception('portfolio token send UI injection failed')
        return response
