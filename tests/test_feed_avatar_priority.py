"""Regression checks for fast feed avatar fetch and reusable photo URLs."""
import ast
import base64
import hashlib
import io
from pathlib import Path
import sqlite3
import tempfile
import urllib.parse
from flask import Flask, make_response, request
from PIL import Image

root = Path(__file__).resolve().parents[1]
source = (root/'dashboard.py').read_text()
js = (root/'static/dashboard.js').read_text()
ux = (root/'static/app-ux.js').read_text()
functions = {}
for node in ast.parse(source).body:
    if isinstance(node, ast.FunctionDef) and node.name in ('_feed_avatar_photo_url', 'public_avatar_photo'):
        # Run the actual route body against an isolated local test database.
        node.decorator_list = []
        functions[node.name] = node
assert len(functions) == 2
with tempfile.TemporaryDirectory() as tmp:
    db = str(Path(tmp)/'avatars.db')
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE users (wallet_address TEXT PRIMARY KEY, avatar_url TEXT)')
    buf = io.BytesIO()
    Image.new('RGB',(24,24),(30,50,75)).save(buf,'JPEG')
    photo = buf.getvalue()
    uri = 'data:image/jpeg;base64,'+base64.b64encode(photo).decode()
    conn.execute('INSERT INTO users VALUES (?,?)',('walletABC',uri))
    conn.commit()
    conn.close()
    app = Flask(__name__)
    env = {'app':app, 'DB_FILE':db, 'sqlite3':sqlite3, 'hashlib':hashlib,
           'urllib':urllib, 'base64':base64, 'binascii':__import__('binascii'),
           're':__import__('re'), 'request':request,'make_response':make_response,
           '_verify_image_magic':lambda content: content.startswith(b'\xff\xd8\xff')}
    mod = ast.fix_missing_locations(ast.Module(body=list(functions.values()),type_ignores=[]))
    exec(compile(mod,'dashboard.py','exec'),env)
    app.add_url_rule('/avatar/photo/<wallet>',view_func=env['public_avatar_photo'])
    make_url = env['_feed_avatar_photo_url']
    cache = {}
    url = make_url(uri,'walletABC',cache)
    assert url.startswith('/avatar/photo/walletABC?v=')
    assert len(url) < 65
    assert make_url(uri,'walletABC',cache) == url and len(cache)==1
    assert make_url('/avatar/default/walletABC','walletABC',cache) == '/avatar/default/walletABC'
    client=app.test_client()
    reply=client.get(url)
    assert reply.status_code==200 and reply.data==photo
    assert reply.content_type=='image/jpeg'
    assert 'immutable' in reply.headers['Cache-Control']
    assert client.get('/avatar/photo/walletABC?v=stale').headers['Cache-Control'].endswith('max-age=60')
    assert client.get('/avatar/photo/not_a_real_wallet').status_code==404
    conn=sqlite3.connect(db)
    conn.execute('UPDATE users SET avatar_url=? WHERE wallet_address=?',('data:image/png;base64,AA==','walletABC'))
    conn.commit()
    conn.close()
    assert client.get(url).status_code == 404
assert "original['avatar_url'] = _feed_avatar_photo_url(" in source
assert "item['avatar_url'] = _feed_avatar_photo_url(" in source
assert 'cardIndex < 8' in js and 'fetchpriority="high"' in js
assert "'<span class=\"fc-avatar-ini\"" in js or '<span class="fc-avatar-ini"' in js
assert "img.closest('.fc-avatar,.feed-composer-avatar,.fc-ri-avatar')" in ux
print('PASS distinct feed avatar URLs are reusable and under 65 characters')
print('PASS avatar image route serves correct JPEG bytes with immutable version caching')
print('PASS stale URLs are not immutable and invalid/missing images do not leak data')
print('PASS post/repost avatars prioritized and never show empty circles')
