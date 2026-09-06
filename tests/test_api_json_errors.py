"""An /api/ route must never answer with HTML.

Every fetch in this app does `await r.json()`. When a route crashed, Flask
returned its HTML 500 page, that parse threw, and the throw was caught by a
handler that said "Network error — try again". So a server-side crash was
reported to the user as a connection problem: the retry it advises cannot
help, and nothing on screen says what actually broke.

These build a tiny Flask app with the real handler from dashboard.py bolted
on, and assert that every way a route can fail still comes back as JSON."""
import json, re, sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC  = open(REPO + '/dashboard.py').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException
import traceback

app = Flask(__name__)

m = re.search(r'^@app\.errorhandler\(Exception\)\ndef _api_never_returns_html\(e\):.*?\n(?=@app\.errorhandler)',
              SRC, re.M | re.S)
assert m, 'handler not found'
exec(compile(m.group(0), 'handler', 'exec'),
     {'app': app, 'jsonify': jsonify, 'request': request,
      'HTTPException': HTTPException, 'traceback': traceback, 'print': lambda *a, **k: None})

@app.errorhandler(404)
def _nf(e):
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'msg': 'Not found'}), 404
    return '<!DOCTYPE html>not found', 404

@app.route('/api/boom')
def boom(): raise RuntimeError('something broke deep in a helper')
@app.route('/api/locked')
def locked():
    import sqlite3; raise sqlite3.OperationalError('database is locked')
@app.route('/api/forbidden')
def forbidden():
    from flask import abort; abort(403)
@app.route('/api/fine')
def fine(): return jsonify({'ok': True})
@app.route('/page/boom')
def page_boom(): raise RuntimeError('a page crashed')

app.config['PROPAGATE_EXCEPTIONS'] = False
c = app.test_client()

def body(path):
    r = c.get(path)
    try:
        return r.status_code, json.loads(r.data.decode()), r.data.decode()
    except Exception:
        return r.status_code, None, r.data.decode()

st, d, raw = body('/api/boom')
check('a crashing API route answers 500 with JSON, not an HTML page',
      st == 500 and d is not None)
check('...and the JSON has the ok:false shape every caller already checks',
      d and d.get('ok') is False and d.get('msg'))
check('...and it says the fault is the server\'s, so nobody retries their wifi',
      d and 'connection' in d['msg'].lower())
check('no HTML tag survives into an API response', '<!DOCTYPE' not in raw and '<html' not in raw.lower())

st, d, _ = body('/api/locked')
check('a database error is JSON too, not an HTML page', st == 500 and d and d.get('ok') is False)

st, d, _ = body('/api/forbidden')
check('a deliberate abort(403) keeps its status', st == 403)
check('...and speaks JSON on an API path rather than the default HTML error page',
      d is not None and d.get('ok') is False)

st, d, _ = body('/api/nope')
check('a 404 on an API path still uses its own JSON handler, not this one',
      st == 404 and d and d.get('msg') == 'Not found')

st, d, _ = body('/api/fine')
check('a route that works is untouched', st == 200 and d == {'ok': True})

r = c.get('/page/boom')
check('a crashing PAGE is left alone — this handler only speaks for /api/',
      r.status_code == 500 and b'{' not in r.data[:1])

# ── the call route explains itself instead of crashing ──
call = re.search(r'def api_make_call\(\):.*?\n(?=@app\.route)', SRC, re.S).group(0)
check('the call route catches a database error and asks _sqlite_reason what it '
      'actually was, instead of assuming it is a busy one (tests/test_sqlite_reason.py '
      'covers that mapping)',
      'sqlite3.OperationalError' in call and '_sqlite_reason(e)' in call)
check('...and catches anything else rather than letting it become an HTML 500',
      'except Exception as e:' in call and 'traceback.print_exc()' in call)
check('both log the real cause, so the server log still shows what happened',
      call.count('print(') >= 2)

# ── the page stops calling a server error a network error ──
CALLS = open(REPO + '/templates/calls.html').read()
check('the response body is read as text and parsed, so a non-JSON body no longer '
      'throws into the network-error branch',
      'await r.text()' in CALLS and 'JSON.parse(raw)' in CALLS)
check('a server error names itself and its status instead of blaming the connection',
      "'Server error ' + r.status" in CALLS)
check('"could not reach the server" is now reserved for actually not reaching it',
      'Could not reach the server' in CALLS and 'Network error — try again' not in CALLS)
check('the unparseable body is logged so it can be diagnosed at all',
      'non-JSON response' in CALLS)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
