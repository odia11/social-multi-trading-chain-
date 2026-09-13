"""Fail-closed authorization boundary for money-moving OrcAgent routes.

This layer does not replace the checks inside the trade/bridge/withdraw handlers.
It adds one common invariant in front of them:

* the caller must have a cryptographically authenticated wallet;
* the caller may not override server-owned identity fields in a request;
* object status routes such as bridge status are readable only by the user that
  owns the stored object.

Financial amounts, destination addresses and chain validation remain the job of
the existing route handlers, which already know the exact asset/chain rules.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from flask import jsonify, request

# Identity is derived from the authenticated session and DB. These names are
# never legitimate client authority on a money-moving request. Destination
# fields such as ``to`` / ``to_address`` are intentionally NOT in this set:
# withdrawals are allowed to send to an address the user chooses.
_FORBIDDEN_IDENTITY_KEYS = frozenset({
    'user_id', 'uid', 'wallet', 'wallet_address', 'owner_wallet',
    'from_wallet', 'from_address', 'sender_wallet', 'sender_address',
    'trading_wallet', 'trading_wallet_address', 'evm_wallet', 'evm_address',
    'solana_wallet', 'solana_address', 'account_id', 'owner_id',
})

_BRIDGE_STATUS_RE = re.compile(r'^/api/bridge/status/(\d+)$')


def _auth_wallet(appmod) -> Optional[str]:
    fn = getattr(appmod, '_authenticated_wallet', None)
    if not callable(fn):
        return None
    try:
        value = fn()
    except Exception:
        return None
    return str(value).strip() if value else None


def _uid_for_wallet(appmod, wallet: str) -> Optional[int]:
    getter = getattr(appmod, '_get_uid', None)
    if callable(getter):
        conn = None
        try:
            db = getattr(appmod, '_db', None)
            conn = db() if callable(db) else sqlite3.connect(appmod.DB_FILE)
            uid = getter(conn, wallet)
            return int(uid) if uid else None
        except Exception:
            return None
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    try:
        conn = sqlite3.connect(appmod.DB_FILE)
        try:
            row = conn.execute(
                'SELECT id FROM users WHERE wallet_address=? LIMIT 1',
                (wallet,),
            ).fetchone()
            return int(row[0]) if row else None
        finally:
            conn.close()
    except Exception:
        return None


def _bridge_owner(appmod, bridge_id: int) -> Optional[int]:
    try:
        conn = sqlite3.connect(appmod.DB_FILE)
        try:
            row = conn.execute(
                'SELECT user_id FROM bridge_transactions WHERE id=? LIMIT 1',
                (bridge_id,),
            ).fetchone()
            return int(row[0]) if row and row[0] is not None else None
        finally:
            conn.close()
    except Exception:
        # Fail closed. A DB error must never turn a private bridge status into a
        # public endpoint.
        return None


def _is_financial_path(path: str) -> bool:
    return (
        path == '/api/withdraw' or path.startswith('/api/withdraw/') or
        path == '/api/wallet/send' or path.startswith('/api/wallet/send/') or
        path == '/api/bridge' or path.startswith('/api/bridge/') or
        path == '/api/trade' or path.startswith('/api/trade/') or
        path == '/api/instant-trade' or path.startswith('/api/instant-trade/')
    )


def _request_tries_identity_override() -> bool:
    keys = {str(k).strip().lower() for k in request.args.keys()}
    if request.is_json:
        body = request.get_json(silent=True)
        if isinstance(body, dict):
            keys.update(str(k).strip().lower() for k in body.keys())
    return bool(keys & _FORBIDDEN_IDENTITY_KEYS)


def install(appmod) -> None:
    app = appmod.app
    if getattr(app, '_orca_financial_authorization_hardening_installed', False):
        return
    app._orca_financial_authorization_hardening_installed = True

    @app.before_request
    def _financial_authorization_guard():
        path = request.path or '/'
        if not _is_financial_path(path):
            return None

        wallet = _auth_wallet(appmod)
        if not wallet:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

        # The session/DB decides who is spending. Never let a crafted request
        # nominate another user or another source wallet.
        if _request_tries_identity_override():
            app.logger.warning(
                'financial identity override blocked path=%s wallet=%s',
                path, wallet[:8] + '…' if len(wallet) > 8 else wallet,
            )
            return jsonify({'ok': False, 'error': 'Invalid identity fields'}), 400

        uid = _uid_for_wallet(appmod, wallet)
        if not uid:
            # An authenticated wallet with no server user row is not allowed to
            # move money. This also prevents request-supplied user IDs from
            # bridging the gap.
            return jsonify({'ok': False, 'error': 'Account not available'}), 403

        # Bridge IDs are guessable integers. Treat them as object references,
        # not bearer tokens: only the owner may poll the transaction status.
        match = _BRIDGE_STATUS_RE.match(path)
        if match:
            bridge_id = int(match.group(1))
            owner = _bridge_owner(appmod, bridge_id)
            if owner is None:
                return jsonify({'ok': False, 'error': 'Not found'}), 404
            if owner != uid:
                # Use 404 to avoid confirming that another user's bridge exists.
                return jsonify({'ok': False, 'error': 'Not found'}), 404

        return None
