"""User-scoped portfolio balance for the public OrcAgent profile card.

The shown total is an approximate SOL equivalent of the existing authoritative
Solana portfolio snapshot, converted at the current SOL/USD rate. If token indexing is temporarily
unavailable, the endpoint still returns the profile user's directly verified
Solana SOL trading balance instead of hiding the card. No key, token inventory
or RPC URL is included in the response. All reads are read-only.
"""
from __future__ import annotations

import math
import sqlite3
import time

from flask import jsonify


def _amount(value):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return round(number, 6) if math.isfinite(number) and number >= 0 else None


def _live_sol_fallback(d, wallet: str, user_id: int):
    """Return a real Solana SOL balance even when token indexing is down.

    Public profiles should not become "Unavailable" merely because the
    wallet-wide token indexer is throttled. The dedicated trading wallet's
    native SOL account can be read with ordinary unindexed RPC calls.
    """
    onchain_wallet = d._get_trading_wallet_address(wallet) or wallet
    stale = False
    try:
        available = d._get_user_sol(onchain_wallet)
    except Exception:
        raise ValueError('SOL balance unavailable')
    available = _amount(available)
    if available is None:
        raise ValueError('Solana SOL balance unavailable')
    return {
        'ok': True,
        'user_id': user_id,
        'portfolio_value_sol_approx': available,
        'available_sol': max(0, available - d.SOL_NETWORK_RESERVE),
        'other_assets_sol_approx': None,
        'generated_at': time.time(),
        'stale': stale,
        'partial': True,
        'scope': 'solana_sol',
        'unit': 'SOL',
        'approximate': False,
    }


STAFF_ROLES = frozenset({'admin','executive','moderator','analyst'})


def can_view_profile_balance(d, wallet, viewer):
    """A team balance is visible only to its authenticated owner."""
    if viewer and viewer == wallet:
        return True
    try:
        if wallet == getattr(d,'ADMIN_WALLET',None) or wallet in getattr(d,'OWNER_WALLETS',()):
            return False
        with sqlite3.connect(d.DB_FILE,timeout=8.0) as conn:
            columns={r[1] for r in conn.execute('PRAGMA table_info(users)')}
            role=None
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_roles'").fetchone():
                row=conn.execute('SELECT role FROM admin_roles WHERE wallet_address=?',(wallet,)).fetchone()
                if row:
                    role=row[0]
            if role is None and 'role' in columns:
                row=conn.execute('SELECT role FROM users WHERE wallet_address=?',(wallet,)).fetchone()
                role=row[0] if row else None
        if str(role or '').strip().lower() in STAFF_ROLES:
            return False
        lookup=getattr(d,'get_user_role',None)
        return not callable(lookup) or str(lookup(wallet)).strip().lower() not in STAFF_ROLES
    except Exception:
        # Role lookup failure must not expose a possibly privileged wallet.
        return False


def install(d):
    app = d.app
    if getattr(app, '_orca_profile_portfolio_balance_installed', False):
        return
    app._orca_profile_portfolio_balance_installed = True

    @app.get('/api/profile/<int:user_id>/portfolio-balance')
    @d.rate_limit(20, 60)
    def profile_portfolio_balance(user_id):
        conn = sqlite3.connect(d.DB_FILE, timeout=8.0)
        conn.row_factory = sqlite3.Row
        try:
            columns = {r['name'] for r in conn.execute('PRAGMA table_info(users)')}
            selected = ['wallet_address']
            selected += [name for name in ('profile_private', 'private_profile',
                                           'is_profile_private', 'hide_portfolio_balance')
                         if name in columns]
            row = conn.execute(
                'SELECT ' + ','.join(selected) + ' FROM users WHERE id=? LIMIT 1',
                (user_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            return jsonify({'ok': False, 'error': 'Profile not found'}), 404
        wallet = str(row['wallet_address'] or '')
        if not wallet:
            return jsonify({'ok': False, 'error': 'Portfolio unavailable'}), 503
        viewer = d._authenticated_wallet()
        if not can_view_profile_balance(d,wallet,viewer) or (viewer != wallet and any(bool(row[name]) for name in selected[1:])):
            response=jsonify({'ok':False,'error':'Portfolio balance is private'})
            response.headers['Cache-Control']='private, no-store'
            return response,403

        # Public profile views need one fast, dependable number. Do not make a
        # visitor wait for the wallet-wide indexed token scan just to show the
        # user's SOL balance; read the dedicated trading wallet's native
        # SOL account directly. Own-profile views still prefer the richer full
        # portfolio snapshot below.
        if viewer != wallet:
            try:
                result = _live_sol_fallback(d, wallet, user_id)
                response = jsonify(result)
                response.headers['Cache-Control'] = 'private, no-store'
                return response
            except Exception:
                return jsonify({'ok': False, 'error': 'Portfolio balance temporarily unavailable'}), 503

        from portfolio_multichain_holdings import _portfolio_snapshot
        try:
            snap = _portfolio_snapshot(d, wallet)
            value = _amount(snap.get('total_sol'))
            available = _amount(snap.get('available_to_trade_sol'))
            if available is None:
                raise ValueError('Solana SOL balance unavailable')
            if value is None or available is None:
                raise ValueError('Incomplete portfolio valuation')
            others = round(max(0.0, value - available), 6)
            result = {
                'ok': True, 'user_id': user_id,
                'portfolio_value_sol_approx': value,
                'available_sol': available,
                'other_assets_sol_approx': others,
                'generated_at': snap.get('generated_at'),
                'stale': bool(snap.get('stale')),
                'partial': False,
                'scope': 'solana_portfolio',
                'unit': 'SOL',
                'approximate': True,
            }
        except Exception:
            # A wallet-wide token indexer outage must not hide the one balance
            # we can verify cheaply and directly: the profile user's Solana
            # SOL trading balance. Never invent other-token value here.
            try:
                result = _live_sol_fallback(d, wallet, user_id)
            except Exception:
                return jsonify({'ok': False, 'error': 'Portfolio balance temporarily unavailable'}), 503

        response = jsonify(result)
        response.headers['Cache-Control'] = 'private, no-store'
        return response
