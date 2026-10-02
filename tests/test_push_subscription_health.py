import os, sqlite3, sys, tempfile, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({
    'DATA_DIR': tempfile.mkdtemp(),
    'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
    'ORCAGENT_FRONTS_GAS': '0',
})
import app_entry  # noqa: E402
from solders.keypair import Keypair  # noqa: E402

d = app_entry._dashboard
app = app_entry.app
checks = []
def check(name, cond):
    checks.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)

wallet = str(Keypair().pubkey())
uid = d.get_or_create_user(wallet)
CSRF = 'tok' * 10
BASE = 'https://orcagent.fun'

def dbrow(endpoint):
    with sqlite3.connect(d.DB_FILE) as c:
        return c.execute(
            '''SELECT failure_count,last_failure_status,disabled,last_success_at
               FROM push_subscriptions WHERE endpoint=?''', (endpoint,)
        ).fetchone()

bad = 'https://push.example/bad'
good = 'https://push.example/good'
with sqlite3.connect(d.DB_FILE) as c:
    c.execute('''INSERT INTO push_subscriptions(user_id,endpoint,p256dh,auth)
                 VALUES (?,?,?,?)''', (uid, bad, 'p', 'a'))

class FakeResponse:
    status_code = 400
class FakeWebPushError(Exception):
    def __init__(self):
        super().__init__('400 Bad Request')
        self.response = FakeResponse()

d._PYWEBPUSH_OK = True
d.VAPID_PRIVATE_KEY = 'test-key'
d.WebPushException = FakeWebPushError
def fail_push(**_):
    raise FakeWebPushError()
d.webpush = fail_push

d._send_push_notification_sync(uid, 't', 'b')
r = dbrow(bad)
check('one HTTP 400 is recorded but not quarantined', r[:3] == (1, 400, 0))

d._send_push_notification_sync(uid, 't', 'b')
d._send_push_notification_sync(uid, 't', 'b')
r = dbrow(bad)
check('three consecutive HTTP 400s quarantine only that endpoint',
      r[:3] == (3, 400, 1))

client = app.test_client()
with client.session_transaction(base_url=BASE) as s:
    s['wallet'] = wallet
    s['user_id'] = uid
    s['csrf_token'] = CSRF
resp = client.post('/api/push/subscribe', base_url=BASE,
                   headers={'X-CSRF-Token': CSRF},
                   json={'endpoint': good, 'keys': {'p256dh': 'p2', 'auth': 'a2'},
                         'previous_endpoint': bad})
check('re-registering current browser succeeds',
      resp.status_code == 200 and resp.get_json().get('ok'))
with sqlite3.connect(d.DB_FILE) as c:
    old = c.execute('SELECT 1 FROM push_subscriptions WHERE endpoint=?', (bad,)).fetchone()
    new = c.execute('''SELECT failure_count,disabled,last_seen_at
                       FROM push_subscriptions WHERE endpoint=?''', (good,)).fetchone()
check('endpoint rotation removes only this account previous endpoint', old is None)
check('new endpoint starts active and healthy',
      new is not None and new[0] == 0 and new[1] == 0 and new[2] is not None)

# A successful delivery resets a transient failure counter.
with sqlite3.connect(d.DB_FILE) as c:
    c.execute('''UPDATE push_subscriptions
                 SET failure_count=2,last_failure_status=400
                 WHERE endpoint=?''', (good,))
d.webpush = lambda **_: None
d._send_push_notification_sync(uid, 't', 'b')
r = dbrow(good)
check('successful push clears prior failure state',
      r[0] == 0 and r[1] == 0 and r[2] == 0 and r[3] is not None)

# Status/test endpoints count only active subscriptions.
with sqlite3.connect(d.DB_FILE) as c:
    c.execute('UPDATE push_subscriptions SET disabled=1 WHERE endpoint=?', (good,))
status = client.get('/api/push/status?endpoint=' + good, base_url=BASE).get_json()
check('disabled endpoint is not reported as an active device',
      status['devices'] == 0 and status['this_device'] is False)

raise SystemExit(0 if all(checks) else 1)
