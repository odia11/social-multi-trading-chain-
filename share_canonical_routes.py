"""Canonical sharing fixes for OrcAgent.

Keeps permanent app links attached to X shares and gives profiles a stable
user-id route that survives username changes.
"""
from contextvars import ContextVar
from functools import wraps
import os
import sqlite3
from urllib.parse import quote


_share_link = ContextVar('orca_share_link', default='')
_INSTALLED = False


def _public_base_url():
    return (os.getenv('ORCAGENT_PUBLIC_URL') or 'https://orcagent.fun').rstrip('/')


def _append_canonical_link(text, link, limit=280):
    text = (text or '').strip()
    if not link or link in text:
        return text
    suffix = ' ' + link
    if len(text) + len(suffix) <= limit:
        return text + suffix
    keep = max(0, limit - len(suffix) - 1)
    trimmed = text[:keep].rstrip()
    if trimmed:
        trimmed += '…'
    return (trimmed + suffix).strip()


def _find_feed_share_endpoint(app):
    for rule in app.url_map.iter_rules():
        if rule.rule == '/api/feed/share-to-x/<path:post_id>':
            return rule.endpoint
    return None


def _profile_user_id(dashboard_module, identifier):
    conn = sqlite3.connect(dashboard_module.DB_FILE)
    try:
        row = conn.execute(
            'SELECT id FROM users WHERE wallet_address=? OR username=? LIMIT 1',
            (identifier, identifier),
        ).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def _profile_wallet(dashboard_module, user_id):
    conn = sqlite3.connect(dashboard_module.DB_FILE)
    try:
        row = conn.execute(
            'SELECT wallet_address FROM users WHERE id=? LIMIT 1',
            (int(user_id),),
        ).fetchone()
        return row[0] if row and row[0] else None
    finally:
        conn.close()


def install(dashboard_module):
    """Install narrow, concurrency-safe runtime adapters on the Flask app."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = dashboard_module.app
    original_post_to_x = dashboard_module._post_to_x

    @wraps(original_post_to_x)
    def _post_to_x_with_canonical_link(wallet, text, media_ids=None):
        # The old feed route appended link_fallback only when media upload
        # failed. A successful image therefore removed the route back to the
        # post. The request wrapper below puts the permanent post URL in this
        # ContextVar; this layer applies it regardless of media success.
        link = _share_link.get()
        if link:
            text = _append_canonical_link(text, link)
        return original_post_to_x(wallet, text, media_ids=media_ids)

    dashboard_module._post_to_x = _post_to_x_with_canonical_link

    endpoint = _find_feed_share_endpoint(app)
    if endpoint and endpoint in app.view_functions:
        original_feed_share = app.view_functions[endpoint]

        @wraps(original_feed_share)
        def _feed_share_with_canonical_context(*args, **kwargs):
            post_id = kwargs.get('post_id')
            if post_id is None and args:
                post_id = args[0]
            link = _public_base_url() + '/post/' + quote(str(post_id or ''), safe='')
            token = _share_link.set(link)
            try:
                return original_feed_share(*args, **kwargs)
            finally:
                _share_link.reset(token)

        app.view_functions[endpoint] = _feed_share_with_canonical_context

    # Permanent profile route. Usernames are editable; numeric user IDs are
    # not. Render the existing profile page directly so /u/<id> remains the
    # browser URL instead of redirecting back to a rename-sensitive handle.
    if 'canonical_profile_by_id' not in app.view_functions:
        @app.route('/u/<int:user_id>', endpoint='canonical_profile_by_id')
        def canonical_profile_by_id(user_id):
            wallet = _profile_wallet(dashboard_module, user_id)
            if not wallet:
                return dashboard_module.make_response('Profile not found', 404)
            return dashboard_module.profile_view(wallet)

    # The existing template's Share Profile button uses window.location.href.
    # Replace just that rendered assignment with the permanent /u/<id> URL.
    # This also repairs old /profile/<username> visits without rewriting the
    # large template file itself.
    @app.after_request
    def _canonical_profile_share_url(response):
        try:
            from flask import request
            if response.status_code != 200 or not response.mimetype == 'text/html':
                return response
            path = request.path or ''
            user_id = None
            if path.startswith('/u/'):
                try:
                    user_id = int(path.split('/', 2)[2])
                except (TypeError, ValueError, IndexError):
                    user_id = None
            elif path.startswith('/profile/'):
                identifier = path[len('/profile/'):]
                if identifier:
                    user_id = _profile_user_id(dashboard_module, identifier)
            if not user_id:
                return response

            body = response.get_data(as_text=True)
            old = 'var url = window.location.href;'
            if old not in body:
                return response
            stable = _public_base_url() + '/u/' + str(user_id)
            body = body.replace(old, 'var url = ' + repr(stable) + ';', 1)
            response.set_data(body)
            response.content_length = len(response.get_data())
        except Exception as exc:
            app.logger.warning('canonical profile share patch skipped: %s', exc)
        return response
