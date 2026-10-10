"""Read-only, bounded history of confirmed Solana wallet transfers.

History distinguishes real incoming/outgoing SPL transfers from swaps and from
OrcAgent tips, which already have their own authoritative transaction ledger.
No keys, signing, blockchain writes or gas sponsorship.
"""
from __future__ import annotations

import sqlite3
import threading
import time

from flask import jsonify

USDC = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
_CACHE = {}
_GUARD = threading.Lock()
_ACCOUNT_CURSOR = {}
_TOKEN_ACCOUNTS = {}
_TX_CACHE = {}
_TTL_SECONDS = 75


def _owner_usdc_balance(meta, key, owner):
    result = 0
    for entry in meta.get(key) or []:
        if entry.get('mint') != USDC or entry.get('owner') != owner:
            continue
        value = (entry.get('uiTokenAmount') or {}).get('amount')
        try:
            result += int(value or 0)
        except (TypeError, ValueError):
            continue
    return result


def _other_token_moved(meta, owner):
    for side in ('preTokenBalances', 'postTokenBalances'):
        for entry in meta.get(side) or []:
            if entry.get('owner') == owner and entry.get('mint') != USDC:
                return True
    return False


def _native_balance_moved(meta, tx, owner):
    keys = (((tx or {}).get('transaction') or {}).get('message') or {}).get('accountKeys') or []
    for i, entry in enumerate(keys):
        address = entry.get('pubkey') if isinstance(entry, dict) else entry
        if address != owner:
            continue
        pre = meta.get('preBalances') or []
        post = meta.get('postBalances') or []
        if i < len(pre) and i < len(post):
            # Ignore a normal network fee; sizable SOL changes mean this
            # is likely a swap or a rent-creating transfer, not plain USDC.
            return abs((int(post[i])-int(pre[i])) / 1e9) > 0.00005
    return False


def _wallet_events(d, wallet, *, since=None):
    import portfolio_token_withdraw as tip

    try:
        owner = str(d._get_trading_wallet_address(wallet) or wallet)
    except Exception:
        owner = wallet
    try:
        from solders.pubkey import Pubkey
        Pubkey.from_string(owner)
    except Exception:
        return []

    def rpc(method, params):
        # History must not occupy request threads with 15-second demo-provider
        # retries. A failed token index must not disable native SOL detection.
        preferred = 'https://solana-rpc.publicnode.com' if method != 'getTokenAccountsByOwner' else None
        return tip._rpc_call_any(d, method, params, timeout=4, preferred_url=preferred,
                                 max_providers=3, skip_demo=True)

    accounts = [owner]
    with _GUARD:
        accounts.extend(_TOKEN_ACCOUNTS.get(owner, []))
    for program in (d.TOKEN_PROGRAM_ID, d.TOKEN_2022_PROGRAM_ID):
        try:
            token_result, _ = rpc('getTokenAccountsByOwner',
                [owner, {'programId': program}, {'encoding': 'jsonParsed', 'commitment': 'confirmed'}])
        except Exception:
            continue
        for value in (token_result or {}).get('value') or []:
            addr = value.get('pubkey')
            if addr and addr not in accounts:
                accounts.append(addr)
    # A known USDC ATA can be queried even when indexed discovery is blocked.
    try:
        from solders.pubkey import Pubkey
        token_program = Pubkey.from_string(d.TOKEN_PROGRAM_ID)
        ata_program = Pubkey.from_string('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL')
        ata, _ = Pubkey.find_program_address(
            [bytes(Pubkey.from_string(owner)), bytes(token_program), bytes(Pubkey.from_string(USDC))], ata_program)
        if str(ata) not in accounts:
            accounts.append(str(ata))
    except (ValueError, TypeError):
        pass
    with _GUARD:
        _TOKEN_ACCOUNTS[owner] = accounts[1:]
        if len(_TOKEN_ACCOUNTS) > 1000:
            oldest = next(iter(_TOKEN_ACCOUNTS))
            _TOKEN_ACCOUNTS.pop(oldest, None)
            _ACCOUNT_CURSOR.pop(oldest, None)

    # Rotate token accounts across bounded checks instead of issuing one RPC
    # per holding on every poll. Always include native-wallet signatures.
    with _GUARD:
        cursor = _ACCOUNT_CURSOR.get(owner, 0)
        token_accounts = accounts[1:]
        selected = [owner]
        if token_accounts:
            selected += [token_accounts[(cursor+i) % len(token_accounts)]
                         for i in range(min(3, len(token_accounts)))]
            _ACCOUNT_CURSOR[owner] = (cursor+3) % len(token_accounts)
    signatures = {}
    for addr in selected:
        try:
            result, _ = rpc(
                'getSignaturesForAddress',
                [addr, {'limit': 15, 'commitment': 'confirmed'}])
        except Exception:
            if addr == owner:
                raise
            continue
        for row in result or []:
            signature = row.get('signature')
            if not signature or row.get('err'):
                continue
            signatures[signature] = max(
                int(row.get('blockTime') or 0), signatures.get(signature, 0))

    conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
    try:
        known = set()
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(tip_transactions)")}
        if 'tx_hash' in cols:
            known = {r[0] for r in conn.execute(
                """SELECT tx_hash FROM tip_transactions
                   WHERE sender_wallet=? OR recipient_wallet=?
                   OR sender_user_id=(SELECT id FROM users WHERE wallet_address=?)
                   OR recipient_user_id=(SELECT id FROM users WHERE wallet_address=?)""",
                (wallet, wallet, wallet, wallet))}
    except sqlite3.Error:
        known = set()
    finally:
        conn.close()

    events = []
    started = time.monotonic()
    candidates = sorted(signatures.items(), key=lambda row: row[1], reverse=True)
    if since is not None:
        candidates = [(sig, ts) for sig, ts in candidates if not ts or ts >= since]
    for sig, timestamp in candidates[:(32 if since is not None else 8)]:
        # Historical reads are optional UI data, never worth timing out the
        # live wallet app or starving the provider for trading RPC calls.
        if time.monotonic() - started > 8:
            break
        if sig in known:
            continue
        with _GUARD:
            cached = _TX_CACHE.get(sig)
        tx = cached[1] if cached and time.monotonic()-cached[0] < 300 else None
        if tx is None:
            try:
                tx, _ = rpc('getTransaction',
                    [sig, {'encoding': 'jsonParsed', 'commitment': 'confirmed',
                           'maxSupportedTransactionVersion': 0}])
            except Exception:
                continue
            if isinstance(tx, dict):
                with _GUARD:
                    _TX_CACHE[sig] = (time.monotonic(), tx)
                    if len(_TX_CACHE) > 2048:
                        _TX_CACHE.pop(next(iter(_TX_CACHE)), None)
        if not isinstance(tx, dict):
            continue
        meta = tx.get('meta') or {}
        if meta.get('err') is not None:
            continue
        message = (tx.get('transaction') or {}).get('message') or {}
        # jsonParsed still leaves ComputeBudget / Token-2022 instructions
        # partially decoded. Resolve their program IDs instead of rejecting
        # a normal transfer just because an instruction has no `program`.
        programs = {
            '11111111111111111111111111111111': 'system',
            'ComputeBudget111111111111111111111111111111': 'compute-budget',
            str(d.TOKEN_PROGRAM_ID): 'spl-token',
            str(d.TOKEN_2022_PROGRAM_ID): 'spl-token-2022',
            'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL': 'spl-associated-token-account',
            'MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr': 'spl-memo',
            'Memo1UhkJRfHyvLMcVucJwxXeuD728EqVDDwQDxFMNo': 'spl-memo',
        }
        instructions = [dict(ix, program=programs.get(ix.get('programId'), ix.get('program')))
                        for ix in message.get('instructions') or [] if isinstance(ix, dict)]
        # Plain native sends only. Do not label rent funding, swaps or launch
        # transactions as an incoming/outgoing payment.
        if instructions and all(ix.get('program') in ('system', 'compute-budget', 'spl-memo') for ix in instructions):
            native_raw = 0
            for ix in instructions:
                parsed = ix.get('parsed') or {}
                info = parsed.get('info') or {}
                if parsed.get('type') == 'transfer':
                    if info.get('source') == owner:
                        native_raw -= int(info.get('lamports') or 0)
                    if info.get('destination') == owner:
                        native_raw += int(info.get('lamports') or 0)
            if native_raw:
                events.append({'id':'solana-sol:'+sig,
                    'type':'receive' if native_raw>0 else 'send',
                    'title':'Received SOL' if native_raw>0 else 'Sent SOL',
                    'amount':abs(native_raw)/1e9, 'currency':'SOL', 'chain':'solana',
                    'status':'confirmed', 'tx_hash':sig,
                    'timestamp':int(tx.get('blockTime') or signatures[sig]),
                    'subtitle':'To your wallet' if native_raw>0 else 'From your wallet',
                    'explorer_url':tip._explorer('solana',sig)})
                continue
        # Only direct token transfers: do not mislabel swaps/launches as deposits.
        allowed = ('system', 'compute-budget', 'spl-memo', 'spl-token',
                   'spl-token-2022', 'spl-associated-token-account')
        if not instructions or any(ix.get('program') not in allowed for ix in instructions):
            continue
        balances = {}
        for side, sign in (('preTokenBalances', -1), ('postTokenBalances', 1)):
            for entry in meta.get(side) or []:
                if entry.get('owner') != owner:
                    continue
                amount = entry.get('uiTokenAmount') or {}
                mint = entry.get('mint')
                if not mint or 'amount' not in amount or 'decimals' not in amount:
                    continue
                row = balances.setdefault(mint, [0, int(amount['decimals'])])
                row[0] += sign * int(amount['amount'])
        for mint, (raw, decimals) in balances.items():
            if not raw:
                continue
            currency = 'USDC' if mint == USDC else 'tokens'
            events.append({'id': 'solana:'+mint+':'+sig,
                'type': 'receive' if raw > 0 else 'send',
                'title': ('Received ' if raw > 0 else 'Sent ') + currency,
                'subtitle': 'To your wallet' if raw > 0 else 'From your wallet',
                'amount': abs(raw) / 10**decimals, 'currency': currency,
                'mint': mint, 'chain': 'solana', 'timestamp': int(tx.get('blockTime') or timestamp),
                'tx_hash': sig, 'explorer_url': tip._explorer('solana', sig),
                'status': 'confirmed'})

    return sorted(events, key=lambda e: e['timestamp'], reverse=True)[:(64 if since is not None else 16)]


def install(d):
    app = d.app
    if getattr(app, '_orca_wallet_activity_installed', False):
        return
    app._orca_wallet_activity_installed = True

    @app.get('/api/portfolio/wallet-activity')
    def wallet_activity_history():
        wallet = d._authenticated_wallet()
        if not wallet:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        with _GUARD:
            cached = _CACHE.get(wallet)
            if cached and time.monotonic() - cached[0] < _TTL_SECONDS:
                return jsonify({'ok': True, 'events': cached[1], 'scope': 'solana-payments'})
        try:
            events = _wallet_events(d, wallet)
        except Exception:
            return jsonify({'ok': False, 'error': 'Wallet history temporarily unavailable',
                            'events': [], 'scope': 'solana-payments'}), 503
        with _GUARD:
            _CACHE[wallet] = (time.monotonic(), events)
        return jsonify({'ok': True, 'events': events, 'scope': 'solana-payments'})
