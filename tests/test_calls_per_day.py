"""Five calls a day per member (was three).

The limit lives in one place, CALLS_PER_DAY_LIMIT: the server enforces it,
/api/calls/mine reports it next to what is left, and the call sheet and the
Calls tab draw "x of 5 left" from that reply instead of a number in the JS.
"""
import os, sqlite3, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

B = 'https://orcagent.fun'; CSRF = 'x' * 40
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
c.commit(); c.close()
cl = app.test_client()
with cl.session_transaction(base_url=B) as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF

def made_today(n):
    c = sqlite3.connect(d.DB_FILE)
    for _ in range(n):
        c.execute("INSERT INTO token_calls (user_id, wallet, mint, price_at_call, peak_price) VALUES (?,?,?,1,1)",
                  (uid, w, str(Keypair().pubkey())))
    c.commit(); c.close()

def mine():
    return cl.get('/api/calls/mine', base_url=B).get_json()

check('the limit is five a day', d.CALLS_PER_DAY_LIMIT == 5)
m = mine()
check('a member starts the day with 5 of 5, and the reply says the limit',
      m['calls_left_today'] == 5 and m['calls_per_day'] == 5)
made_today(4)
check('after four calls one is left -- where three used to be the end', mine()['calls_left_today'] == 1)
made_today(1)
r = cl.post('/api/calls', json={'mint': str(Keypair().pubkey())}, headers={'X-CSRF-Token': CSRF}, base_url=B)
check('the sixth call of the day is refused, naming the limit',
      r.status_code == 429 and '(5/day)' in r.get_json()['msg'] and mine()['calls_left_today'] == 0)

js = open(os.path.join(ROOT, 'static', 'feed-calls.js'), encoding='utf-8').read()
check('the call sheet and Calls tab take the limit from the server, no "3" in the JS',
      'if(d.calls_per_day > 0) perDay = d.calls_per_day;' in js
      and "' of ' + perDay + ' calls left today'" in js and 'i < perDay; i++' in js
      and "left + ' of ' + perDay + ' left'" in js
      and 'of 3' not in js and "'3 per day'" not in js)
raise SystemExit(0 if all(checks) else 1)
