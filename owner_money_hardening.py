"""Owner-only guard for money-moving admin actions.

Role-based admin access is useful for moderation/analysis, but collecting fees,
transferring treasury funds or changing sponsor balances must never be delegated
implicitly to a moderator/analyst/admin role. OWNER_WALLET is the hard boundary.
"""
from __future__ import annotations

import os

from flask import jsonify, request

_MUTATING = {'POST', 'PUT', 'PATCH', 'DELETE'}
_MONEY_WORDS = (
    'collect-fees', 'collect_fees', 'payout', 'withdraw', 'transfer', 'treasury',
    'gas-sponsor', 'gas_sponsor', 'fee-wallet', 'fee_wallet', 'refund', 'sweep',
)


def _owners():
    return {x.strip() for x in os.getenv('OWNER_WALLET', '').split(',') if x.strip()}


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_owner_money_hardening_installed', False):
        return
    app._orca_owner_money_hardening_installed = True

    @app.before_request
    def _owner_money_guard():
        if request.method not in _MUTATING:
            return None
        path = (request.path or '').lower()
        if not path.startswith('/api/admin/') or not any(word in path for word in _MONEY_WORDS):
            return None
        owners = _owners()
        if not owners:
            return jsonify({'ok': False, 'error': 'OWNER_WALLET is not configured'}), 503
        fn = getattr(dashboard_module, '_authenticated_wallet', None)
        wallet = fn() if callable(fn) else None
        if not wallet:
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401
        if wallet not in owners:
            app.logger.warning('owner-only money action denied path=%s wallet=%s', path, str(wallet)[:8] + '…')
            return jsonify({'ok': False, 'error': 'Owner wallet required'}), 403
        return None
