"""User-scoped portfolio balance for the public OrcAgent profile card.

The shown total is an approximate USDC equivalent of the existing authoritative
USD portfolio snapshot (1 USDC ~ 1 USD); available USDC is the actual
cross-chain stablecoin total. No sender wallet, key, token inventory or RPC URL
is included in the response. All reads are read-only.
"""
from __future__ import annotations

import math
import sqlite3

from flask import jsonify


def _amount(value):
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return round(number, 6) if math.isfinite(number) and number >= 0 else None


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
        if viewer != wallet and any(bool(row[name]) for name in selected[1:]):
            return jsonify({'ok': False, 'error': 'Portfolio balance is private'}), 403

        from portfolio_multichain_holdings import _portfolio_snapshot
        try:
            snap = _portfolio_snapshot(d, wallet)
            value = _amount(snap.get('total_usd'))
            # The shared Portfolio snapshot includes trading stables such as
            # Robinhood's USDG in available_to_trade_usdc. A public label
            # saying 'Available USDC' must only contain actual USDC, never
            # silently add USDG or other stablecoin balances.
            stables = snap.get('stable')
            if isinstance(stables, dict) and isinstance(stables.get('evm_chains'), dict):
                available = _amount(stables.get('solana_usdc'))
                if available is None:
                    raise ValueError('Solana USDC balance unavailable')
                chains = getattr(d, 'EVM_CHAINS', {})
                for chain, balance in stables['evm_chains'].items():
                    cfg = chains.get(chain, {})
                    if str(cfg.get('usdc_symbol') or 'USDC').upper() != 'USDC':
                        continue
                    part = _amount(balance)
                    if part is None:
                        raise ValueError('Chain USDC balance unavailable')
                    available += part
                available = round(available, 6)
            else:
                # Retain compatibility with an older complete snapshot.
                available = _amount(snap.get('available_to_trade_usdc'))
            if value is None or available is None:
                raise ValueError('Incomplete portfolio valuation')
            others = round(max(0.0, value - available), 6)
            result = {
                'ok': True, 'user_id': user_id,
                'portfolio_value_usdc_approx': value,
                'available_usdc': available,
                'other_assets_usdc_approx': others,
                'generated_at': snap.get('generated_at'),
                'stale': bool(snap.get('stale')),
                'unit': 'USDC',
                'approximate': True,
            }
            response = jsonify(result)
            response.headers['Cache-Control'] = 'private, no-store'
            return response
        except Exception:
            # RPC failures or partial snapshots must not be presented as zero.
            return jsonify({'ok': False, 'error': 'Portfolio balance temporarily unavailable'}), 503
