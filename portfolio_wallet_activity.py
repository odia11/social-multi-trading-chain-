"""Read-only, bounded history of actual canonical Solana USDC wallet transfers.

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


def _wallet_events(d, wallet):
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

    token_result, _ = tip._rpc_call_any(
        d, 'getTokenAccountsByOwner',
        [owner, {'mint': USDC}, {'encoding': 'jsonParsed', 'commitment': 'confirmed'}])
    accounts = [owner]
    for value in (token_result or {}).get('value') or []:
        addr = value.get('pubkey')
        if addr and addr not in accounts:
            accounts.append(addr)

    signatures = {}
    for addr in accounts[:4]:
        try:
            result, _ = tip._rpc_call_any(
                d, 'getSignaturesForAddress',
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
    for sig, timestamp in sorted(signatures.items(), key=lambda row: row[1], reverse=True)[:8]:
        # Historical reads are optional UI data, never worth timing out the
        # live wallet app or starving the provider for trading RPC calls.
        if time.monotonic() - started > 8:
            break
        if sig in known:
            continue
        try:
            tx, _ = tip._rpc_call_any(
                d, 'getTransaction',
                [sig, {'encoding': 'jsonParsed', 'commitment': 'confirmed',
                       'maxSupportedTransactionVersion': 0}])
        except Exception:
            continue
        if not isinstance(tx, dict):
            continue
        meta = tx.get('meta') or {}
        if meta.get('err') is not None:
            continue
        raw = (_owner_usdc_balance(meta, 'postTokenBalances', owner) -
               _owner_usdc_balance(meta, 'preTokenBalances', owner))
        if not raw or _other_token_moved(meta, owner) or _native_balance_moved(meta, tx, owner):
            continue
        value = raw / 1_000_000
        events.append({
            'id': 'solana-usdc:' + sig,
            'type': 'receive' if raw > 0 else 'send',
            'title': 'Received USDC' if raw > 0 else 'Sent USDC',
            'subtitle': 'To your wallet' if raw > 0 else 'From your wallet',
            'amount': value,
            'currency': 'USDC',
            'chain': 'solana',
            'timestamp': int(tx.get('blockTime') or timestamp),
            'tx_hash': sig,
            'explorer_url': 'https://solscan.io/tx/' + sig,
            'status': 'confirmed',
        })
    return sorted(events, key=lambda e: e['timestamp'], reverse=True)[:16]


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
                return jsonify({'ok': True, 'events': cached[1], 'scope': 'solana-usdc'})
        try:
            events = _wallet_events(d, wallet)
        except Exception:
            return jsonify({'ok': False, 'error': 'Wallet history temporarily unavailable',
                            'events': [], 'scope': 'solana-usdc'}), 503
        with _GUARD:
            _CACHE[wallet] = (time.monotonic(), events)
        return jsonify({'ok': True, 'events': events, 'scope': 'solana-usdc'})
