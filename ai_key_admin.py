"""The Anthropic API key, settable from the Admin Console.

Without ANTHROPIC_API_KEY in the server environment, every AI feature (the
conversational @orcagent, AI token analysis) was off, and setting it meant
editing the environment on the server. An admin can now paste the key on
Admin -> Platform assistant:

- it is stored encrypted with the app's ENCRYPTION_KEY (Fernet), never in
  plain text, and never shown again -- only its last four characters;
- it is checked against the API before it is saved; a key the API rejects
  is not stored;
- it takes effect immediately, for every AI feature, without a restart;
- an ANTHROPIC_API_KEY set in the environment always wins over a stored key.
"""
from __future__ import annotations

import re
import sqlite3
import time

from flask import jsonify, request

CONFIG_KEY = 'anthropic_api_key_enc'
KEY_SHAPE = re.compile(r'^sk-ant-[A-Za-z0-9_\-]{20,200}$')
_state = {'source': None}


def _stored(d):
    try:
        with sqlite3.connect(d.DB_FILE, timeout=5) as c:
            c.execute('CREATE TABLE IF NOT EXISTS server_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            row = c.execute('SELECT value FROM server_config WHERE key=?', (CONFIG_KEY,)).fetchone()
        if not row:
            return ''
        return d._fernet.decrypt(row[0].encode()).decode()
    except Exception:
        return ''


def _activate(d, key, source):
    d.ANTHROPIC_API_KEY = key
    _state['source'] = source if key else None
    try:
        with d._anthropic_auth_lock:
            d._anthropic_auth_state['failed'] = False
    except Exception:
        pass


def load(d):
    """At startup: the environment key wins; otherwise use the stored one."""
    if getattr(d, 'ANTHROPIC_API_KEY', ''):
        _state['source'] = 'environment'
        return
    key = _stored(d)
    if key:
        _activate(d, key, 'admin')


def status(d):
    key = getattr(d, 'ANTHROPIC_API_KEY', '') or ''
    failed = False
    try:
        failed = bool(d._anthropic_auth_state.get('failed'))
    except Exception:
        pass
    return {
        'configured': bool(key),
        'source': _state['source'] if key else None,
        'hint': ('…' + key[-4:]) if key else '',
        'rejected_by_api': failed,
    }


def verify(d, key):
    """'ok', 'rejected' (the API said no) or 'unreachable' (could not check)."""
    try:
        resp = d.requests.post(
            d._ANTHROPIC_URL,
            headers={**d._ANTHROPIC_HEADERS, 'x-api-key': key},
            json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 1,
                  'messages': [{'role': 'user', 'content': 'ping'}]},
            timeout=10,
        )
    except Exception:
        return 'unreachable'
    code = getattr(resp, 'status_code', 0)
    if code in (401, 403):
        return 'rejected'
    return 'ok' if code < 500 else 'unreachable'


def install(d):
    app = d.app
    if getattr(app, '_orca_ai_key_admin', False):
        return
    app._orca_ai_key_admin = True
    load(d)

    def guard():
        err = d._require_role('admin', 'executive')
        if err:
            return err
        if request.method != 'GET' and not d._validate_csrf(request.headers.get('X-CSRF-Token', '')):
            return jsonify(ok=False, error='CSRF validation failed'), 403
        if request.method != 'GET' and callable(getattr(d, '_rate_ok', None)) \
                and not d._rate_ok('ai_key_admin:' + str(d._authenticated_wallet()), 10, 3600):
            return jsonify(ok=False, error='Too many attempts. Try again later.'), 429
        return None

    @app.route('/api/admin/platform-assistant/ai-key', methods=['GET', 'POST', 'DELETE'])
    def ai_key():
        err = guard()
        if err:
            return err
        if request.method == 'GET':
            return jsonify(ok=True, **status(d))
        if request.method == 'DELETE':
            with sqlite3.connect(d.DB_FILE, timeout=5) as c:
                c.execute('DELETE FROM server_config WHERE key=?', (CONFIG_KEY,))
            if _state['source'] == 'admin':
                _activate(d, '', None)
            return jsonify(ok=True, **status(d))
        key = str((request.get_json(silent=True) or {}).get('key') or '').strip()
        if not KEY_SHAPE.match(key):
            return jsonify(ok=False, error='That does not look like an Anthropic API key (sk-ant-…).'), 400
        result = verify(d, key)
        if result == 'rejected':
            return jsonify(ok=False, error='Anthropic rejected this key. Nothing was saved.'), 400
        with sqlite3.connect(d.DB_FILE, timeout=5) as c:
            c.execute('CREATE TABLE IF NOT EXISTS server_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            c.execute('INSERT OR REPLACE INTO server_config (key, value) VALUES (?,?)',
                      (CONFIG_KEY, d._fernet.encrypt(key.encode()).decode()))
        if _state['source'] != 'environment':
            _activate(d, key, 'admin')
        try:
            d.add_log('[admin] Anthropic API key updated by an admin at ' + time.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception:
            pass
        out = status(d)
        out['verified'] = result == 'ok'
        return jsonify(ok=True, **out)
