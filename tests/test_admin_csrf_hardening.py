"""Regression checks for mandatory CSRF validation on admin mutations."""
# Runnable on its own, like every other test here: these import modules from
# the repository root, and `python3 tests/x.py` puts tests/ on the path and
# not the root. Without this the file fails with ModuleNotFoundError and
# reads as a broken test rather than a missing PYTHONPATH.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

from pathlib import Path
from types import SimpleNamespace

from flask import Flask, session

ROOT = Path(__file__).resolve().parents[1]
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')
SRC = (ROOT / 'admin_csrf_hardening.py').read_text(encoding='utf-8')

checks = []
def check(name, ok):
    checks.append(bool(ok)); print(('PASS ' if ok else 'FAIL ') + name)

check('production entry installs admin CSRF guard',
      'admin_csrf_hardening' in ENTRY and '_install_admin_csrf_hardening(_dashboard)' in ENTRY)
check('all state-changing HTTP verbs are covered',
      all(x in SRC for x in ("'POST'", "'PUT'", "'PATCH'", "'DELETE'")))
check('guard covers root and nested admin API routes',
      "path == '/api/admin'" in SRC and "path.startswith('/api/admin/')" in SRC)
check('both historical CSRF header spellings are accepted',
      "X-CSRF-Token" in SRC and "X-CSRFToken" in SRC)
check('invalid CSRF fails closed',
      "'CSRF validation failed'" in SRC and '403' in SRC)

app = Flask(__name__)
app.secret_key = 'test-secret-for-csrf-guard'

def validate(token):
    return bool(token) and token == session.get('csrf_token')

mod = SimpleNamespace(app=app, _validate_csrf=validate)
from admin_csrf_hardening import install
install(mod)

@app.post('/api/admin/test')
def mutate():
    return {'ok': True}

@app.get('/api/admin/test')
def read():
    return {'ok': True}

with app.test_client() as client:
    with client.session_transaction() as s:
        s['csrf_token'] = 'expected-token'
    r = client.post('/api/admin/test')
    check('missing token is rejected', r.status_code == 403)
    r = client.post('/api/admin/test', headers={'X-CSRF-Token':'wrong'})
    check('wrong token is rejected', r.status_code == 403)
    r = client.post('/api/admin/test', headers={'X-CSRF-Token':'expected-token'})
    check('correct token reaches handler', r.status_code == 200)
    r = client.get('/api/admin/test')
    check('read-only request does not require CSRF', r.status_code == 200)

raise SystemExit(0 if all(checks) else 1)
