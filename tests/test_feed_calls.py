"""Token calls on the home feed.

- The Call button on Home places a call (price fetched by the server, never
  sent by the browser) AND posts it to the feed with the caller's reason.
- The feed shows the call's live numbers (entry, now, peak, multiplier) from
  token_calls -- a post cannot forge them: the __CALL__ marker is refused in
  a normal post, a marker copied into another post shows nothing, and a call
  cannot be edited afterwards.
- The Calls tab lists only call posts; followers are notified.
- The /calls page still places a call WITHOUT posting it (unchanged).
Mocked token data; no network.
"""
import os, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

CSRF, BASE = 'tok' * 10, 'https://orcagent.fun'
H = {'X-CSRF-Token': CSRF}
pushed = []
d._send_push_notifications_bulk = lambda ids, title, body, url='/': pushed.append((list(ids), title, body))
d._send_push_notification = lambda uid, title, body, url='/': pushed.append(([uid], title, body))

MINT = str(Keypair().pubkey())
d.get_token_data = lambda mint, fast=False, chain=None: {
    'symbol': 'SJP', 'name': 'Super Jean Phil', 'price': 0.0001, 'market_cap': 1_800_000,
    'chain': 'solana', 'image_url': 'https://cdn.example/sjp.png'}

def member(name):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = sqlite3.connect(d.DB_FILE); c.execute('UPDATE users SET username=? WHERE id=?', (name, uid)); c.commit(); c.close()
    return w, uid

def client(w, uid):
    c = app.test_client()
    with c.session_transaction(base_url=BASE) as s:
        s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF
    return c

def db(sql, *a):
    c = sqlite3.connect(d.DB_FILE)
    try:
        rows = c.execute(sql, a).fetchall(); c.commit(); return rows
    finally:
        c.close()

aw, au = member('alice'); bw, bu = member('bob')
alice, bob = client(aw, au), client(bw, bu)
db('INSERT INTO follows (follower_id, following_id, notify_enabled) VALUES (?,?,1)', bu, au)

# ── the Call button on Home ──
r = alice.post('/api/calls', json={'mint': MINT, 'note': 'Volume is picking up', 'post_to_feed': True,
                                   'price': 0.00000001}, headers=H, base_url=BASE)
data = r.get_json() or {}
check('a call from Home is placed and posted', r.status_code == 200 and data.get('ok') and data.get('post_id'))
call_id, post_id = data.get('id'), data.get('post_id')
row = db('SELECT price_at_call, note, chain, image_url, post_id FROM token_calls WHERE id=?', call_id)[0]
check('...at the price the SERVER fetched (a sent price is ignored)', row[0] == 0.0001)
check('...with the reason, chain and logo kept', row[1] == 'Volume is picking up' and row[2] == 'solana'
      and row[3] == 'https://cdn.example/sjp.png' and row[4] == post_id)
check('...and 2 of 3 calls are left today', data.get('calls_left_today') == 2)
check("the caller's followers are told", ('follow_post', 'alice called $SJP') in
      db('SELECT type, content FROM notifications WHERE user_id=?', bu)
      and any(p[1] == 'New call' and bu in p[0] for p in pushed))

# the token moves: the peak loop's observations
db('UPDATE token_calls SET peak_price=0.00034, last_price=0.00029 WHERE id=?', call_id)

def feed(c, f='all'):
    return c.get('/api/social/feed?filter=' + f, base_url=BASE).get_json()['items']

item = next(i for i in feed(bob) if i['id'] == post_id and i['type'] != 'repost')
call = item.get('call') or {}
check('the feed post carries the live call numbers', call.get('symbol') == 'SJP' and call.get('multiplier') == 3.4
      and call.get('now_multiplier') == 2.9 and round(call.get('mcap_now')) == 5_220_000
      and round(call.get('mcap_peak')) == 6_120_000 and call.get('mcap_at_call') == 1_800_000)
check('...and the reason is the post text', item['content'].startswith('Volume is picking up\n__CALL__'))

# ── nothing can be forged ──
r = bob.post('/api/feed/post', json={'content': 'lol __CALL__{"id": %d}' % call_id}, headers=H, base_url=BASE)
check('a normal post cannot contain a call marker', r.status_code == 400)
db('INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,datetime("now"))', bw, 'x\n__CALL__{"id": %d}' % call_id)
fake = db('SELECT MAX(id) FROM feed_posts')[0][0]
fake_item = next(i for i in feed(bob) if i['id'] == fake)
check("a marker copied into another post shows no one else's call", 'call' not in fake_item)
r = alice.post('/api/post/%d/edit' % post_id, json={'content': 'I meant another token'}, headers=H, base_url=BASE)
check('a call cannot be edited afterwards', r.status_code == 400
      and 'Volume is picking up' in db('SELECT content FROM feed_posts WHERE id=?', post_id)[0][0])
single = alice.get('/api/feed/post/p%d' % post_id, base_url=BASE).get_json()['post']
check('a deep-linked call post shows its numbers too', (single.get('call') or {}).get('id') == call_id)

# ── Calls tab ──
alice.post('/api/feed/post', json={'content': 'just a normal post'}, headers=H, base_url=BASE)
calls_tab = feed(bob, 'calls')
check('the Calls tab shows only call posts', [i['id'] for i in calls_tab] == [post_id])
bob.post('/api/feed/repost/p%d' % post_id, headers=H, base_url=BASE)
rep = next((i for i in feed(alice) if i['type'] == 'repost'), None)
check('a repost of a call shows the call', rep is not None and (rep['original'].get('call') or {}).get('id') == call_id)

# ── the /calls page is unchanged: no feed post ──
before = db('SELECT COUNT(*) FROM feed_posts')[0][0]
r = alice.post('/api/calls', json={'mint': MINT}, headers=H, base_url=BASE)
check('a call from the /calls page does not post to the feed',
      r.get_json().get('ok') and r.get_json().get('post_id') is None and db('SELECT COUNT(*) FROM feed_posts')[0][0] == before)
top = alice.get('/api/calls/top?window=24h', base_url=BASE).get_json()['calls']
check('top calls link to their feed post', top[0]['post_id'] == post_id and top[0]['image_url'])
r = alice.post('/api/calls', json={'mint': MINT, 'note': 'x' * 281, 'post_to_feed': True}, headers=H, base_url=BASE)
check('a reason over 280 characters is refused', r.status_code == 400)

# ── any token on any chain can be called, even while DexScreener is down ──
from unittest.mock import patch  # noqa: E402
SOL_ADDR = '2KLsQKvwLWsJG95pBQHHJcodsotzkd1MbFYAnKH399qY'   # the address from the report
EVM_ADDR = '0x' + 'ab' * 20
class GT:
    def __init__(self, code, body): self.status_code, self._b = code, body
    def json(self): return self._b
gt_calls = []
def fake_gt(url, headers=None, timeout=None):
    gt_calls.append(url)
    if '/networks/solana/tokens/' + SOL_ADDR in url:
        return GT(200, {'data': {'attributes': {'address': SOL_ADDR, 'symbol': 'CRUMB', 'name': 'Crumb',
                                                'price_usd': '0.00042', 'market_cap_usd': '420000', 'image_url': 'https://x/c.png'}}})
    if '/networks/base/tokens/' + EVM_ADDR in url:
        return GT(200, {'data': {'attributes': {'address': EVM_ADDR, 'symbol': 'BASED', 'name': 'Based',
                                                'price_usd': '1.5', 'fdv_usd': '9000000'}}})
    return GT(404, {})
with patch.object(d, '_dex_get', lambda *a, **k: None), patch.object(d, '_gt_try_take', lambda reserve=0: True), \
        patch.object(d.requests, 'get', side_effect=fake_gt):
    got = alice.get('/api/calls/lookup?q=' + SOL_ADDR, base_url=BASE).get_json()['tokens']
    check('a Solana address DexScreener cannot serve is found via GeckoTerminal',
          got and got[0]['symbol'] == 'CRUMB' and got[0]['chain'] == 'solana' and got[0]['price'] == 0.00042)
    got = alice.get('/api/calls/lookup?q=' + EVM_ADDR, base_url=BASE).get_json()['tokens']
    check('an EVM address is tried on the EVM chains until found (Base)', bool(got) and got[0]['chain'] == 'base'
      and got[0]['price'] == 1.5 and got[0]['market_cap'] == 9_000_000)
    d._scanner_cache['data'] = [{'mint': 'Scan1111111111111111111111111111111111pump', 'symbol': 'SCAN', 'name': 'Scanned',
                                 'chain': 'solana', 'price_usd': 0.01, 'market_cap': 10_000_000, 'image_url': ''}]
    n_before = len(gt_calls)
    got = alice.get('/api/calls/lookup?q=Scan1111111111111111111111111111111111pump', base_url=BASE).get_json()['tokens']
    check("a token already in the app's own market list needs no outside request",
          got and got[0]['symbol'] == 'SCAN' and len(gt_calls) == n_before)
    got = alice.get('/api/calls/lookup?q=sca', base_url=BASE).get_json()['tokens']
    check('...and is found by its ticker too', got and got[0]['symbol'] == 'SCAN')
    orig_td = d.get_token_data
    d.get_token_data = lambda mint, fast=False, chain=None: None
    try:
        r = bob.post('/api/calls', json={'mint': SOL_ADDR, 'chain': 'solana', 'post_to_feed': True}, headers=H, base_url=BASE)
    finally:
        d.get_token_data = orig_td
    row = db('SELECT symbol, price_at_call, mcap_at_call, chain FROM token_calls WHERE mint=?', SOL_ADDR)
    check('...and the call is placed at that server-side price', r.status_code == 200 and row == [('CRUMB', 0.00042, 420000.0, 'solana')])
pairs = [{'chainId': 'solana', 'priceUsd': '9', 'liquidity': {'usd': 1e6},
          'baseToken': {'address': 'Other111111111111111111111111111111111111', 'symbol': 'OTH'},
          'quoteToken': {'address': SOL_ADDR, 'symbol': 'CRUMB'}}]
check("a pool where the address is only the QUOTE token never lends it the other token's price",
      d._call_rows_from_pairs(pairs, want_mint=SOL_ADDR) == [])
src = open(os.path.join(os.path.dirname(__file__), '..', 'dashboard.py')).read()
check('the peak loop falls back to GeckoTerminal for tokens DexScreener did not price',
      "simple/networks/' " in src or "/simple/networks/'" in src)

# ── the page ──
import json, subprocess  # noqa: E402
ROOT = os.path.join(os.path.dirname(__file__), '..')
html = open(os.path.join(ROOT, 'dashboard.html')).read()
dash = open(os.path.join(ROOT, 'static', 'dashboard.js')).read()
check('Home has a Call button in the composer and a Calls tab',
      'id="call-pill-btn"' in html and '_openCallSheet()' in html and 'data-tab="calls"' in html
      and 'id="feed-calls-top"' in html and '/static/feed-calls.js?v=' in html and '/static/feed-calls.css?v=' in html)
check('...and on a phone too', '<button data-feed="calls">Calls</button>' in open(os.path.join(ROOT, 'static', 'home-mobile.js')).read())
check('the feed asks the server for the Calls tab', "_homeFeedFilter === 'calls' ? 'calls'" in dash)
check('the post text never shows the raw marker, and a call cannot be edited',
      "_rawContent.indexOf('__CALL__')" in dash and '!isCallPost && (isOwn || e.is_own)' in dash)
harness = r"""
global.window = global; global.document = {readyState:'complete', getElementById:function(){return null}};
require('%s');
var evil = {id:1, mint:'M"><img src=x onerror=alert(1)>', symbol:'<b>X</b>', name:'<script>', chain:'solana',
            image_url:'javascript:alert(1)', price_at_call:0.0001, peak_price:0.00034, last_price:0.00029,
            multiplier:3.4, now_multiplier:2.9, mcap_at_call:1800000, mcap_now:5220000, mcap_peak:6120000, called_at:''};
console.log(JSON.stringify({html: window._feedCallCardHtml(evil, 'p1'), empty: window._feedCallCardHtml(null, 'p1')}));
""" % os.path.abspath(os.path.join(ROOT, 'static', 'feed-calls.js')).replace('\\', '/')
out = json.loads(subprocess.run(['node', '-e', harness], capture_output=True, text=True, timeout=30).stdout or '{}')
card = out.get('html', '')
check('the call card shows the multiplier and the market caps',
      '3.4x' in card and '$1.8M' in card and '$5.2M' in card and '$6.1M' in card and 'Buy $' in card)
check('...and escapes everything that came from the token', '<b>X</b>' not in card and '<script>' not in card
      and '<img src=x' not in card and 'javascript:' not in card)
check('...and draws nothing for a post without call data', out.get('empty') == '')
raise SystemExit(0 if all(checks) else 1)
