"""Exercise actual photo/session response passes with logged-in cookies."""
import ast
import base64
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
from flask import Flask, g, make_response, request, session
from PIL import Image

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
source = subprocess.check_output(['git', 'show', 'HEAD:dashboard.py'], cwd=root, text=True) if os.getenv('BASELINE') else (root/'dashboard.py').read_text()
nodes = []
for node in ast.parse(source).body:
    if isinstance(node, ast.FunctionDef) and node.name in {'public_avatar_photo', '_persist_remembered_session'}:
        node.decorator_list = []
        nodes.append(node)
assert len(nodes) == 2

with tempfile.TemporaryDirectory() as tmp:
    db = str(Path(tmp)/'photos.db')
    buf = io.BytesIO()
    Image.new('RGB', (24, 24), (225, 175, 80)).save(buf, 'PNG')
    photo = buf.getvalue()
    uri = 'data:image/png;base64,' + base64.b64encode(photo).decode()
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE users (wallet_address TEXT, avatar_url TEXT)')
        conn.execute('INSERT INTO users VALUES (?, ?)', ('publicWallet', uri))
    app = Flask(__name__)
    app.secret_key = 'disposable-test-secret'
    env = dict(DB_FILE=db, sqlite3=sqlite3, hashlib=hashlib, base64=base64,
               binascii=__import__('binascii'), re=__import__('re'),
               make_response=make_response, request=request, g=g, session=session,
               _authenticated_wallet=lambda: session.get('wallet', ''),
               _verify_image_magic=lambda content: content.startswith(b'\x89PNG'))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), 'dashboard.py', 'exec'), env)
    app.add_url_rule('/avatar/photo/<wallet>', view_func=env['public_avatar_photo'])
    app.after_request(env['_persist_remembered_session'])

    @app.before_request
    def read_session():
        session.get('wallet')  # Actual rate/auth hooks also read the session.
        g.device_cookie_written = True
        if request.args.get('change_session'):
            session['setting'] = 'updated'

    @app.route('/api/private-test')
    def private_api():
        return {'wallet': session.get('wallet')}

    @app.route('/other-image')
    def unrelated_image():
        return make_response(photo, 200, {'Content-Type': 'image/png'})

    if not os.getenv('BASELINE'):
        from public_avatar_cache import install
        install(types.SimpleNamespace(app=app))
    url = '/avatar/photo/publicWallet?v=' + hashlib.sha256(uri.encode()).hexdigest()[:16]
    for wallet in ['viewerOne', None, 'viewerTwo']:
        client = app.test_client()
        if wallet:
            with client.session_transaction() as s:
                s['wallet'] = wallet
                s.permanent = True
        response = client.get(url)
        assert response.data == photo and response.status_code == 200
        assert response.headers['Cache-Control'] == 'public, max-age=31536000, immutable', response.headers
        assert 'cookie' not in {v.lower() for v in response.vary}, response.headers
        assert 'Set-Cookie' not in response.headers
        if wallet:
            private = client.get('/api/private-test')
            assert private.json['wallet'] == wallet
            assert 'Cookie' in private.vary
            assert 'no-store' in private.headers['Cache-Control']
            assert 'Set-Cookie' in private.headers
            unrelated = client.get('/other-image')
            assert 'Cookie' in unrelated.vary and 'no-store' in unrelated.headers['Cache-Control']
            changed = client.get(url + '&change_session=1')
            assert 'Set-Cookie' in changed.headers and 'no-store' in changed.headers['Cache-Control']
            with client.session_transaction() as s:
                assert s['setting'] == 'updated' and s['wallet'] == wallet
            invalid = client.get('/avatar/photo/missing')
            assert invalid.status_code == 404 and 'Cookie' in invalid.vary
    print('PASS actual photo route and session hook: guests + permanent signed-in sessions keep public photo cache')
    print('PASS cookie changes do not vary photo bytes; private responses and real session writes remain protected')
