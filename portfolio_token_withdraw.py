"""Withdraw Solana SPL/Token-2022 tokens from Portfolio to another wallet.

The server derives the source trading wallet from the authenticated user,
re-reads the token balance on-chain, validates the recipient, serialises sends,
and never accepts a caller-supplied sender/private key.
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
            'SELECT encrypted_private_key FROM users WHERE wallet_address=? LIMIT 1',
            (wallet,)
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
                + list(getattr(d, '_PROXY_RPCS', []) or [])
                + ['https://solana-rpc.publicnode.com',
                   'https://api.mainnet-beta.solana.com']):
        url = str(url or '').strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _rpc(d):
    urls = _rpc_urls(d)
    return urls[0] if urls else ''



class _SolanaPreflightError(RuntimeError):
    """A rejected Solana transaction, including a bounded, safe RPC diagnosis."""

    def __init__(self, message, *, gas_shortfall=False, reason_code='simulation'):
        super().__init__(message)
        self.gas_shortfall = gas_shortfall
        self.reason_code = reason_code


def _preflight_error_from_rpc(error):
    """Keep the actual simulation failure; never expose arbitrary RPC data."""
    data = error.get('data') if isinstance(error.get('data'), dict) else {}
    failure = data.get('err')
    logs = data.get('logs') if isinstance(data.get('logs'), list) else []
    error_text = str(failure or '')[:140]
    # Take only short program ERROR lines, never full RPC response / URLs.
    lines = [str(line).strip() for line in logs
             if isinstance(line, str) and
             ('failed:' in line.lower() or 'error:' in line.lower()
              or 'insufficient lamports' in line.lower())]
    detail = lines[-1][:140] if lines else ''
    joined = ' '.join((error_text, detail)).lower()
    gas_shortfall = any(term in joined for term in (
        'insufficient lamports', 'insufficient funds for fee',
        'insufficient funds for rent', 'insufficientfundsforrent',
        'insufficientfundsforfee', 'accountnotrentexempt',
        'insufficient funds for transaction fee'))
    blockhash = 'blockhashnotfound' in joined or 'blockhash not found' in joined
    if gas_shortfall:
        label = 'Insufficient SOL for the network fee or token-account rent'
        code = 'insufficient_sol'
    elif blockhash:
        label = 'Recent Solana blockhash expired before submission'
        code = 'expired_blockhash'
    elif failure is not None or detail:
        label = 'Solana rejected the transaction: ' + (detail or error_text)
        code = 'program_rejected'
    else:
        label = 'Solana simulation failed; the RPC did not provide an instruction reason'
        code = 'missing_preflight_details'
    return _SolanaPreflightError(
        label[:235], gas_shortfall=gas_shortfall, reason_code=code)


def _rpc_call(url, method, params):
    r = requests.post(url, json={'jsonrpc':'2.0','id':1,'method':method,'params':params}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError('Solana RPC HTTP %s' % r.status_code)
    body = r.json()
    if body.get('error'):
        error = body['error']
        message = str(error.get('message') or '') if isinstance(error, dict) else str(error)
        if method == 'sendTransaction' and 'simulation failed' in message.lower():
            raise _preflight_error_from_rpc(error)
        raise RuntimeError(message[:220] or 'Solana RPC rejected request')
    if 'result' not in body:
        raise RuntimeError('Solana RPC response missing result')
    return body.get('result')


def _rpc_call_any(d, method, params, require_nonempty=False, preferred_url=None):
    """Read from the first healthy Solana RPC, returning (result, url).

    An empty token-account list is not considered authoritative while other
    configured providers remain, because OrcAgent has observed public RPCs
    return [] while a configured provider immediately returns the real SPL
    accounts.
    """
    last = None
    empty = None
    urls = _rpc_urls(d)
    if preferred_url and preferred_url in urls:
        # A signed transfer's blockhash and preflight should use the same
        # provider first; other providers remain as transport fallbacks.
        urls.remove(preferred_url)
        urls.insert(0, preferred_url)
    for url in urls:
        try:
            result = _rpc_call(url, method, params)
            if require_nonempty:
                value = (result or {}).get('value') if isinstance(result, dict) else None
                if not value:
                    empty = (result, url)
                    continue
            return result, url
        except _SolanaPreflightError:
            # This signed transfer failed preflight. Do not hide its detailed
            # instruction error behind a later provider's 401/429/timeout or
            # resubmit the same rejected transaction to a different RPC.
            raise
        except Exception as exc:
            last = exc
            continue
    if empty is not None:
        return empty
    if last:
        raise last
    raise RuntimeError('No Solana RPC is configured')


def _direct_classic_ata_source(d, owner_text, token_address):
    """Return (entry_or_none, had_authoritative_read) for the classic SPL ATA.

    Public Solana RPCs often reject indexed getTokenAccountsByOwner while still
    serving exact getAccountInfo reads.  A USDC tip should not fail just because
    the indexer is rate-limited when the exact canonical spending account is
    known deterministically.
    """
    from solders.pubkey import Pubkey

    try:
        owner = Pubkey.from_string(owner_text)
        mint = Pubkey.from_string(token_address)
        token_program = Pubkey.from_string(
            str(getattr(d, 'TOKEN_PROGRAM_ID',
                        'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')))
        ata_program = Pubkey.from_string(
            'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
        ata, _ = Pubkey.find_program_address(
            [bytes(owner), bytes(token_program), bytes(mint)], ata_program)
    except Exception:
        return None, False

    # PublicNode is deliberately first only for this exact, read-only account
    # lookup. Indexed methods there require a token, but getAccountInfo is fast
    # and reliable from this production host.
    urls = ['https://solana-rpc.publicnode.com'] + _rpc_urls(d)
    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            result = _rpc_call(url, 'getAccountInfo', [
                str(ata), {'encoding':'base64', 'commitment':'confirmed'}])
            if not isinstance(result, dict) or 'value' not in result:
                continue
            value = result.get('value')
            if value is None:
                return None, True
            if str(value.get('owner') or '') != str(token_program):
                continue
            raw = base64.b64decode(value['data'][0], validate=True)
            if (len(raw) != 165 or raw[:32] != bytes(mint)
                    or raw[32:64] != bytes(owner) or raw[108] != 1):
                continue
            amount_raw = int.from_bytes(raw[64:72], 'little')
            if amount_raw <= 0:
                return None, True
            # Classic USDC is six decimals. For any future classic mint queried
            # here, ask the parsed token balance for its actual decimals.
            decimals = 6
            try:
                bal = _rpc_call(url, 'getTokenAccountBalance',
                                [str(ata), {'commitment':'confirmed'}])
                decimals = int(((bal or {}).get('value') or {}).get('decimals', 6))
            except Exception:
                if str(token_address) != str(getattr(d, 'USDC_MINT', '')):
                    continue
            entry = {
                'pubkey': str(ata),
                'account': {
                    'owner': str(token_program),
                    'data': {'parsed': {'info': {
                        'mint': str(mint), 'owner': str(owner),
                        'state': 'initialized',
                        'tokenAmount': {
                            'amount': str(amount_raw),
                            'decimals': decimals,
                            'uiAmount': amount_raw / (10 ** decimals),
                            'uiAmountString': str(
                                Decimal(amount_raw) / (Decimal(10) ** decimals)),
                        },
                    }}},
                },
            }
            return entry, True
        except Exception:
            continue
    return None, False


def _solana_source_accounts(d, owner_text, token_address):
    """Find funded source accounts using the same fallback as balance reads.

    Filter every response locally. Never combine snapshots across providers,
    and never select an unrelated mint/account from a program-wide scan.
    """
    programs = ('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
                'TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb')

    def matching(result):
        found = []
        for entry in (result or {}).get('value') or []:
            try:
                account = entry['account']
                info = account['data']['parsed']['info']
                if (account['owner'] in programs
                        and info['mint'] == token_address
                        and info['owner'] == owner_text
                        and info.get('state') != 'frozen'
                        and int(info['tokenAmount']['amount']) > 0):
                    found.append(entry)
            except (KeyError, TypeError, ValueError):
                continue
        return found

    # Fast unindexed path first. This is the normal OrcAgent USDC spending
    # account and keeps tips working even when Helius/public indexers are 429.
    direct, direct_valid = _direct_classic_ata_source(d, owner_text, token_address)
    if direct is not None:
        return [direct]
    # OrcAgent's spendable canonical USDC is the associated token account
    # (same invariant as dashboard._get_bot_solana_balances). If an exact,
    # authoritative ATA read says it does not exist/has zero, do not turn a
    # later indexed-provider 429 into a fake "network unavailable" error.
    if direct_valid and str(token_address) == str(getattr(d, 'USDC_MINT', '')):
        return []

    last_error = None
    saw_response = bool(direct_valid)
    for query in [{'mint': token_address}] + [{'programId': p} for p in programs]:
        for url in _rpc_urls(d):
            try:
                result = _rpc_call(url, 'getTokenAccountsByOwner', [
                    owner_text, query, {'encoding': 'jsonParsed', 'commitment': 'confirmed'}])
                if not isinstance(result, dict) or not isinstance(result.get('value'), list):
                    raise RuntimeError('Invalid Solana token-account response')
                saw_response = True
                accounts = matching(result)
                if accounts:
                    return accounts
            except Exception as exc:
                last_error = exc
    if not saw_response and last_error:
        raise RuntimeError('Solana source token accounts are unavailable') from last_error
    return []


def _solana_transfer(d, wallet, token_address, to_address, amount,
                     allow_user_funded_gas=False):
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
    accounts = _solana_source_accounts(d, owner_text, token_address)
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

    # Require the sender's own SOL for both tx fee and, when needed, the
    # recipient ATA rent. A tiny non-zero SOL balance is NOT enough to create
    # a missing token account.
    native, _ = _rpc_call_any(
        d, 'getBalance', [owner_text, {'commitment':'confirmed'}])
    lamports = int((native or {}).get('value') or 0)
    required_lamports = _fee_payer_rent_lamports(d) + 20_000
    if not dest_info or not dest_info.get('value'):
        try:
            rent, _ = _rpc_call_any(
                d, 'getMinimumBalanceForRentExemption', [165])
            required_lamports += int(rent or 2_100_000)
        except Exception:
            required_lamports += 2_100_000
    if lamports < required_lamports:
        # User-authorised Portfolio withdrawals may use the same existing
        # Jupiter gasless bootstrap as tips. Reserve the entire outgoing USDC
        # amount first, so network gas never reduces the requested transfer.
        # Tips have their own bootstrap under the tip lock and leave this
        # optional transfer behavior off to avoid spending gas twice.
        if not allow_user_funded_gas:
            raise ValueError(
                'Not enough SOL in your trading wallet to pay the network fee and token-account rent')
        topup = getattr(d, '_gasless_solana_native_topup', None)
        if not callable(topup):
            raise ValueError('Solana user-funded network gas is unavailable')
        usdc_balance = Decimal(str(d._get_solana_usdc_balance(owner_text)))
        reserved = amount if token_address == d.USDC_MINT else Decimal('0')
        spare = usdc_balance - reserved
        if spare < Decimal('0.20'):
            raise ValueError(
                'Not enough spare USDC to create Solana network gas while keeping the full send amount')
        target_sol = max(
            Decimal('0.0035'),
            Decimal(required_lamports + 500_000) / Decimal(1_000_000_000))
        try:
            topup(wallet, spare, target_sol=float(target_sol))
        except Exception as exc:
            raise ValueError('Unable to create Solana network gas from spare USDC') from exc
        refreshed, _ = _rpc_call_any(
            d, 'getBalance', [owner_text, {'commitment':'confirmed'}])
        lamports = int((refreshed or {}).get('value') or 0)
        if lamports < required_lamports:
            raise ValueError('SOL top-up was submitted but sufficient gas is not yet confirmed; check your balance before retrying')

    bh_result, blockhash_rpc = _rpc_call_any(d, 'getLatestBlockhash', [{'commitment':'confirmed'}])
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
    }], preferred_url=blockhash_rpc)
    return str(sig), float(Decimal(send_raw) / scale)




def _explorer(chain, tx_hash):
    return 'https://solscan.io/tx/' + tx_hash if chain == 'solana' and tx_hash else ''


def _user_tip_wallets(d, user_id):
    conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
    try:
        row = conn.execute(
            'SELECT wallet_address FROM users WHERE id=?',
            (int(user_id),)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    session_wallet = str(row[0] or '')
    try:
        solana_wallet = str(d._get_trading_wallet_address(session_wallet) or session_wallet)
    except Exception:
        solana_wallet = session_wallet
    return {'session': session_wallet, 'solana': solana_wallet}


# Solana rejects any transaction that leaves the fee payer holding more than
# zero but less than the rent-exempt minimum of a plain wallet (0 data bytes,
# 890,880 lamports today): "InsufficientFundsForRent, account_index 0". A
# wallet at 890,946 lamports therefore cannot pay even a 5,000-lamport fee,
# although it "has SOL". Every SOL check below counts this floor.
_FEE_PAYER_RENT_FALLBACK = 890_880
_fee_payer_rent_cache = {'value': 0, 'at': 0.0}


def _fee_payer_rent_lamports(d):
    now = time.time()
    if _fee_payer_rent_cache['value'] and now - _fee_payer_rent_cache['at'] < 3600:
        return _fee_payer_rent_cache['value']
    try:
        rent, _ = _rpc_call_any(d, 'getMinimumBalanceForRentExemption', [0])
        value = int(rent or 0)
        if value <= 0:
            raise ValueError('empty rent answer')
    except Exception:
        return _FEE_PAYER_RENT_FALLBACK
    _fee_payer_rent_cache.update(value=value, at=now)
    return value


def _tip_required_lamports(d, owner_text, recipient_text):
    """SOL required for a canonical-USDC tip, including ATA rent if needed."""
    from solders.pubkey import Pubkey

    try:
        owner = Pubkey.from_string(owner_text)
        recipient = Pubkey.from_string(recipient_text)
        mint = Pubkey.from_string(d.USDC_MINT)
        token_program = Pubkey.from_string(
            str(getattr(d, 'TOKEN_PROGRAM_ID',
                        'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')))
        ata_program = Pubkey.from_string(
            'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
        dest_ata, _ = Pubkey.find_program_address(
            [bytes(recipient), bytes(token_program), bytes(mint)], ata_program)
        dest_info, _ = _rpc_call_any(
            d, 'getAccountInfo', [str(dest_ata), {'encoding':'base64'}])
        # The wallet's own rent-exempt floor plus signature/transaction
        # headroom, plus the recipient's token-account rent when it is new.
        required = _fee_payer_rent_lamports(d) + 20_000
        if not dest_info or not dest_info.get('value'):
            try:
                rent, _ = _rpc_call_any(
                    d, 'getMinimumBalanceForRentExemption', [165])
                required += int(rent or 2_100_000)
            except Exception:
                required += 2_100_000
        return required
    except Exception:
        # Conservative fallback: the wallet's own floor, a new classic SPL
        # token account and the transaction itself.
        return _FEE_PAYER_RENT_FALLBACK + 2_120_000


def _tip_solana_ready(d, sender_wallet, amount, recipient_wallet):
    try:
        owner = str(d._get_trading_wallet_address(sender_wallet) or '')
        if not owner:
            return None
    except Exception:
        return None

    # A failed chain read is UNKNOWN, never an empty wallet. Use the same
    # validated source accounts as the transfer instead of cached UI totals.
    try:
        accounts = _solana_source_accounts(d, owner, str(d.USDC_MINT))
        balance = sum((
            Decimal(entry['account']['data']['parsed']['info']['tokenAmount']['amount'])
            / (Decimal(10) ** int(entry['account']['data']['parsed']['info']['tokenAmount']['decimals']))
            for entry in accounts), Decimal('0'))
    except Exception as exc:
        raise RuntimeError(
            'Cannot verify Solana USDC: the blockchain provider is unavailable or rate-limited. '
            'Your balance is unknown, not zero. Please try again later.') from exc
    if balance < amount:
        return None
    try:
        native, _ = _rpc_call_any(
            d, 'getBalance', [owner, {'commitment':'confirmed'}])
        if not isinstance(native, dict) or not isinstance(native.get('value'), int):
            raise ValueError('Invalid SOL balance response')
        lamports = native['value']
    except Exception as exc:
        raise RuntimeError('Cannot verify the SOL network-fee balance. Please try again later.') from exc

    required_lamports = _tip_required_lamports(
        d, owner, str(recipient_wallet or ''))
    return {
        'chain':'solana', 'balance':balance,
        'native_ready': lamports >= required_lamports,
        'lamports': lamports,
        'required_lamports': required_lamports,
    }


def _needs_sol_message(sol, amount):
    """Plain advice when a Solana tip lacks network gas and spare USDC."""
    spare_needed = Decimal('0.20')
    max_tip = (sol['balance'] - spare_needed).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    add_usdc = (amount + spare_needed - sol['balance']).quantize(Decimal('0.01'))
    if add_usdc <= 0:
        add_usdc = Decimal('0.01')
    text = ('Solana needs a tiny bit of SOL in your trading wallet for the network fee. '
            'OrcAgent converts it from USDC automatically, but that needs $0.20 USDC '
            'next to the tip. ')
    if max_tip >= Decimal('0.01'):
        text += 'You can tip up to $%s right now, ' % max_tip
        text += 'or add $%s USDC to send $%s.' % (add_usdc, amount.quantize(Decimal('0.01')))
    else:
        text += 'Add $%s USDC (or 0.002 SOL) to your trading wallet and try again.' % add_usdc
    return text




def _record_tip(d, sender_wallet, sender_user_id, recipient_user_id,
                recipient_wallet, amount, chain, tx_hash, note='', currency='USDC'):
    # RPC submission gives only a signature, not a confirmed payment.
    # The confirmation watcher reconciles the real chain result separately.
    from tip_experience import record_submitted
    return record_submitted(d, sender_wallet, sender_user_id,
                            recipient_user_id, recipient_wallet, amount,
                            chain, tx_hash, note=note, currency=currency)


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
        if body.get('currency') != 'SOL':
            return jsonify({'ok':False,'error':'Refresh the app: tips now use SOL'}), 409
        amount = _amount(body.get('amount'))
        if amount is None:
            return jsonify({'ok':False,'error':'Enter a positive SOL amount'}), 400
        if amount > Decimal('100'):
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

        lock = _lock_for(sender_wallet, 'solana')
        if not lock.acquire(blocking=False):
            return jsonify({'ok':False,'error':'Another tip is already in progress'}), 409
        try:
            from sol_native_payments import native_transfer, lamports
            try:
                lamports(amount)
                recipient_address = recipient['solana']
                tx_hash, sent = native_transfer(d, sender_wallet, recipient_address, amount, body.get('request_id'))
                chain = 'solana'
            except _SolanaPreflightError as exc:
                return jsonify({'ok':False,'error':str(exc),'reason_code':exc.reason_code,'status':'failed'}), 400
            except ValueError as exc:
                return jsonify({'ok':False,'error':str(exc)}), 400

            with _RECENT_GUARD:
                _RECENT[key] = time.time()
            tip_id = _record_tip(
                d, sender_wallet, sender_user_id, recipient_user_id,
                recipient_address, sent, chain, tx_hash,
                currency='SOL', note=str(body.get('message') or '')[:100])
            try:
                d._wallet_tokens_cache.pop(sender_wallet, None)
                d._wallet_tokens_cache.pop(recipient['session'], None)
            except Exception:
                pass
            try:
                d.add_user_log(sender_wallet,
                    'TIP: %.9f SOL sent to user %s · tx %s' %
                    (float(sent), recipient_user_id, tx_hash[:12]))
            except Exception:
                pass
            return jsonify({
                'ok':True, 'amount_sent':sent, 'max_spend_sol':str(amount), 'currency':'SOL',
                'chain':chain, 'tx_hash':tx_hash, 'tip_id':tip_id,
                'status':'submitted',
                'explorer':_explorer(chain, tx_hash)
            })
        except Exception as exc:
            app.logger.warning('user tip failed wallet=%s error=%s',
                               sender_wallet[:8] + '…', type(exc).__name__)
            return jsonify({'ok':False,'error':'Tip submission unavailable. Check Activity before retrying.'}), 502
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
        if chain != 'solana':
            return jsonify({'ok':False,'error':'OrcAgent supports Solana only'}), 400
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
            tx_hash, sent = _solana_transfer(
                d, wallet, token_address, to_address, amount,
                allow_user_funded_gas=False)
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
            tag = '<script src="/static/portfolio-token-send.js?v=%s" defer %s></script>' % (getattr(d, '_APP_VERSION', 'sol-native-2'), marker)
            html = html.replace('</body>', tag + '</body>', 1) if '</body>' in html else html + tag
            response.set_data(html)
            response.content_length = len(response.get_data())
        except Exception:
            app.logger.exception('portfolio token send UI injection failed')
        return response
