"""Server-side authorization and IDOR hardening for OrcAgent.

This layer is defense-in-depth around the existing route handlers. It keeps the
privileged admin guard and adds object-level ownership checks for destructive or
state-changing user resources (messages, notifications, posts and group
moderation). Existing route-level checks still remain authoritative; this guard
prevents a missed check from turning a numeric object id into an IDOR.
"""
from __future__ import annotations

import os
import re
import sqlite3

from flask import jsonify, request, session

_ADMIN_ROLES = frozenset({'admin', 'executive', 'moderator', 'analyst'})
_MUTATING = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_GROUP_MANAGER_ACTIONS = frozenset({
    'delete', 'update', 'settings', 'set-official', 'pin', 'unpin',
    'kick', 'remove-member', 'ban', 'unban', 'promote', 'demote',
})


def _owner_wallets() -> set[str]:
    return {w.strip() for w in os.getenv('OWNER_WALLET', '').split(',') if w.strip()}


def _connect(dashboard_module):
    db_file = getattr(dashboard_module, 'DB_FILE', None)
    if not db_file:
        return None
    conn = sqlite3.connect(db_file, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn, table: str) -> set[str]:
    try:
        return {str(r[1]) for r in conn.execute('PRAGMA table_info(' + table + ')')}
    except Exception:
        return set()


def _table_exists(conn, table: str) -> bool:
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table,),
        ).fetchone() is not None
    except Exception:
        return False


def _role_for_wallet(dashboard_module, wallet: str) -> str:
    if not wallet:
        return 'user'
    if wallet in _owner_wallets():
        return 'admin'
    try:
        conn = _connect(dashboard_module)
        if conn is None:
            return 'user'
        try:
            row = conn.execute(
                'SELECT role FROM users WHERE wallet_address=? LIMIT 1',
                (wallet,),
            ).fetchone()
            return str(row[0] or 'user').strip().lower() if row else 'user'
        finally:
            conn.close()
    except Exception:
        return 'user'


def _identity(dashboard_module):
    """Return only a cryptographically authenticated wallet + its DB user id."""
    auth_fn = getattr(dashboard_module, '_authenticated_wallet', None)
    wallet = auth_fn() if callable(auth_fn) else None
    if not wallet:
        return None, None

    uid = session.get('user_id')
    try:
        uid = int(uid) if uid is not None else None
    except (TypeError, ValueError):
        uid = None

    if uid is None:
        try:
            conn = _connect(dashboard_module)
            if conn is not None:
                try:
                    row = conn.execute(
                        'SELECT id FROM users WHERE wallet_address=? LIMIT 1',
                        (wallet,),
                    ).fetchone()
                    uid = int(row[0]) if row else None
                finally:
                    conn.close()
        except Exception:
            uid = None
    return str(wallet), uid


def _deny(status: int, message: str):
    return jsonify({'ok': False, 'error': message}), status


def _row_owned_by(conn, table: str, row_id: int, uid: int | None, wallet: str) -> bool | None:
    """Return True/False when schema proves ownership; None when unknown."""
    if not _table_exists(conn, table):
        return None
    cols = _table_columns(conn, table)
    if 'id' not in cols:
        return None

    owner_cols = []
    for name in ('user_id', 'sender_id', 'author_id', 'created_by', 'owner_id'):
        if name in cols and uid is not None:
            owner_cols.append((name, uid))
    for name in ('wallet', 'wallet_address', 'sender_wallet', 'author_wallet', 'owner_wallet'):
        if name in cols:
            owner_cols.append((name, wallet))
    if not owner_cols:
        return None

    row = conn.execute('SELECT * FROM ' + table + ' WHERE id=? LIMIT 1', (row_id,)).fetchone()
    if row is None:
        return False
    return any(str(row[col]) == str(value) for col, value in owner_cols)


def _message_owned(conn, message_id: int, uid: int | None, wallet: str) -> bool | None:
    for table in ('messages', 'direct_messages', 'dm_messages'):
        result = _row_owned_by(conn, table, message_id, uid, wallet)
        if result is not None:
            return result
    return None


def _notification_ids_owned(conn, ids: list[int], uid: int | None, wallet: str) -> bool | None:
    if not ids or not _table_exists(conn, 'notifications'):
        return None
    cols = _table_columns(conn, 'notifications')
    if 'id' not in cols:
        return None
    owner_col, owner_val = None, None
    if uid is not None and 'user_id' in cols:
        owner_col, owner_val = 'user_id', uid
    elif 'wallet' in cols:
        owner_col, owner_val = 'wallet', wallet
    elif 'wallet_address' in cols:
        owner_col, owner_val = 'wallet_address', wallet
    if not owner_col:
        return None
    placeholders = ','.join('?' for _ in ids)
    rows = conn.execute(
        f'SELECT id FROM notifications WHERE id IN ({placeholders}) AND {owner_col}=?',
        tuple(ids) + (owner_val,),
    ).fetchall()
    return len(rows) == len(set(ids))


def _group_manager(conn, group_id: int, uid: int | None) -> bool | None:
    if uid is None or not _table_exists(conn, 'groups'):
        return None
    cols = _table_columns(conn, 'groups')
    if 'id' not in cols:
        return None
    row = conn.execute('SELECT * FROM groups WHERE id=? LIMIT 1', (group_id,)).fetchone()
    if row is None:
        return False
    for col in ('created_by', 'owner_id', 'user_id'):
        if col in cols and str(row[col]) == str(uid):
            return True

    for membership_table in ('group_members', 'group_memberships'):
        if not _table_exists(conn, membership_table):
            continue
        mcols = _table_columns(conn, membership_table)
        if not {'group_id', 'user_id'}.issubset(mcols):
            continue
        member = conn.execute(
            f'SELECT * FROM {membership_table} WHERE group_id=? AND user_id=? LIMIT 1',
            (group_id, uid),
        ).fetchone()
        if not member:
            return False
        if 'role' not in mcols:
            return False
        return str(member['role'] or '').lower() in {'owner', 'admin', 'moderator', 'mod'}
    return False


def _group_post_owned_or_manager(conn, group_id: int, post_id: int, uid: int | None, wallet: str) -> bool | None:
    manager = _group_manager(conn, group_id, uid)
    if manager is True:
        return True
    for table in ('group_posts', 'posts'):
        result = _row_owned_by(conn, table, post_id, uid, wallet)
        if result is not None:
            return result
    return manager


def install(dashboard_module):
    app = dashboard_module.app
    if getattr(app, '_orca_authorization_hardening_installed', False):
        return
    app._orca_authorization_hardening_installed = True

    @app.before_request
    def _privileged_and_idor_guard():
        path = request.path or '/'
        method = request.method.upper()

        privileged = (
            path == '/admin' or path.startswith('/admin/') or
            path == '/api/admin' or path.startswith('/api/admin/') or
            path == '/bridge-test' or path.startswith('/bridge-test/')
        )
        if privileged:
            wallet, _uid = _identity(dashboard_module)
            if not wallet:
                return _deny(401, 'Authentication required') if path.startswith('/api/') else ('Authentication required', 401)
            role = _role_for_wallet(dashboard_module, wallet)
            if role not in _ADMIN_ROLES:
                app.logger.warning('authorization denied path=%s wallet=%s role=%s', path, wallet[:8] + '…', role)
                return _deny(403, 'Forbidden') if path.startswith('/api/') else ('Forbidden', 403)
            return None

        if method not in _MUTATING:
            return None

        protected_prefixes = (
            '/api/messages', '/api/notifications/mine', '/api/copy-trade',
            '/api/groups', '/api/watchlist', '/api/posts',
        )
        if not path.startswith(protected_prefixes):
            return None

        wallet, uid = _identity(dashboard_module)
        if not wallet:
            return _deny(401, 'Authentication required')

        try:
            conn = _connect(dashboard_module)
            if conn is None:
                return _deny(503, 'Authorization backend unavailable')
            try:
                # Editing/deleting a message by numeric message id must only
                # ever affect a message authored by the authenticated user.
                m = re.fullmatch(r'/api/messages/(\d+)', path)
                if m and method in {'PUT', 'PATCH', 'DELETE'}:
                    owned = _message_owned(conn, int(m.group(1)), uid, wallet)
                    if owned is False:
                        app.logger.warning('IDOR blocked message=%s wallet=%s', m.group(1), wallet[:8] + '…')
                        return _deny(403, 'Forbidden')

                # Bulk notification deletion is restricted to the caller's
                # own notification rows even when ids are manually altered.
                if path == '/api/notifications/mine/delete_batch':
                    body = request.get_json(silent=True) or {}
                    raw_ids = body.get('ids') or []
                    try:
                        ids = [int(x) for x in raw_ids]
                    except (TypeError, ValueError):
                        return _deny(400, 'Invalid notification ids')
                    owned = _notification_ids_owned(conn, ids, uid, wallet)
                    if owned is False:
                        app.logger.warning('IDOR blocked notification batch wallet=%s', wallet[:8] + '…')
                        return _deny(403, 'Forbidden')

                # Ordinary posts may only be edited/deleted by their author.
                p = re.fullmatch(r'/api/posts/(\d+)', path)
                if p and method in {'PUT', 'PATCH', 'DELETE'}:
                    owned = _row_owned_by(conn, 'posts', int(p.group(1)), uid, wallet)
                    if owned is False:
                        app.logger.warning('IDOR blocked post=%s wallet=%s', p.group(1), wallet[:8] + '…')
                        return _deny(403, 'Forbidden')

                # Group manager actions require creator/group moderator rights.
                g = re.match(r'^/api/groups/(\d+)(?:/(.*))?$', path)
                if g:
                    group_id = int(g.group(1))
                    tail = (g.group(2) or '').strip('/')
                    action = tail.split('/', 1)[0] if tail else ''
                    post_match = re.fullmatch(r'posts/(\d+)', tail)
                    if post_match and method in {'PUT', 'PATCH', 'DELETE'}:
                        allowed = _group_post_owned_or_manager(conn, group_id, int(post_match.group(1)), uid, wallet)
                        if allowed is False:
                            app.logger.warning('IDOR blocked group-post=%s group=%s wallet=%s', post_match.group(1), group_id, wallet[:8] + '…')
                            return _deny(403, 'Forbidden')
                    elif action in _GROUP_MANAGER_ACTIONS:
                        allowed = _group_manager(conn, group_id, uid)
                        if allowed is False:
                            app.logger.warning('IDOR blocked group action=%s group=%s wallet=%s', action, group_id, wallet[:8] + '…')
                            return _deny(403, 'Forbidden')
            finally:
                conn.close()
        except sqlite3.Error:
            # An authorization DB failure must not silently authorize a
            # destructive request. Existing read routes are unaffected.
            app.logger.exception('authorization DB error path=%s', path)
            return _deny(503, 'Authorization backend unavailable')

        return None
