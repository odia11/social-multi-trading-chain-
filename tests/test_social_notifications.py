"""Members are notified when someone tips them, messages them or @tags them.

- a direct message, an @tag in a post and a confirmed tip each create a
  notification for the recipient (these already worked -- guarded here);
- an @tag in a REPLY did not notify the tagged member at all (fixed);
- phone (web push) notifications need a VAPID key pair, and nothing ever
  created one, so no phone ever got a push: deploy/install.sh now creates
  the pair once when the env file has none, and never replaces one.
"""
import os, re, sqlite3, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
import tip_experience as te  # noqa: E402
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

CSRF, BASE = 'tok' * 10, 'https://orcagent.fun'   # session cookie is Secure, scoped to .orcagent.fun
H = {'X-CSRF-Token': CSRF}

pushed = []
d._send_push_notification = lambda uid, title, body, url='/': pushed.append((uid, title, body))

def member(name):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = sqlite3.connect(d.DB_FILE); c.execute('UPDATE users SET username=? WHERE id=?', (name, uid)); c.commit(); c.close()
    return w, uid

def client(w, uid):
    c = app.test_client()
    with c.session_transaction(base_url=BASE) as s:
        s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF
    return c

def notes(uid):
    c = sqlite3.connect(d.DB_FILE)
    rows = c.execute('SELECT type, content FROM notifications WHERE user_id=? ORDER BY id', (uid,)).fetchall()
    c.close(); return rows

aw, au = member('alice'); bw, bu = member('bob'); cw, cu = member('carol')
alice = client(aw, au)

r = alice.post(f'/api/messages/{bu}', json={'message': 'hey bob'}, headers=H, base_url=BASE)
check('a direct message is sent', r.status_code == 200 and r.get_json().get('ok'))
check('...and notifies the recipient', ('message', 'alice: hey bob') in notes(bu))

r = alice.post('/api/feed/post', json={'content': 'gm @bob'}, headers=H, base_url=BASE)
check('a post is created', r.status_code == 200 and r.get_json().get('ok'))
check('...and @bob is notified of the tag', ('mention', 'alice mentioned you in a post') in notes(bu))

c = sqlite3.connect(d.DB_FILE); post = c.execute('SELECT MAX(id) FROM feed_posts').fetchone()[0]; c.close()
pushed.clear()
r = alice.post('/api/feed/reply', json={'post_id': 'p%d' % post, 'message': '@carol @Bob what do you think? @nobody @alice'},
               headers=H, base_url=BASE)
check('a reply is created', r.status_code == 200 and r.get_json().get('ok'))
check('@carol tagged in a reply is notified (was missing)', ('mention', 'alice mentioned you in a reply') in notes(cu))
check('tags are case-insensitive (@Bob)', ('mention', 'alice mentioned you in a reply') in notes(bu))
check('...with a phone push too', any(p[0] == cu and p[1] == 'New mention' for p in pushed))
check('tagging yourself notifies nobody', not any(n[0] == 'mention' for n in notes(au)))

tid = te.record_submitted(d, aw, au, cu, cw, 0.25, 'solana', '5' * 88, 'nice')
te._transition(d, tid, 'confirmed')
check('a confirmed tip notifies the recipient', ('tip', 'alice sent you 0.25 USDC · nice') in notes(cu))

# Phone push: install.sh creates a VAPID pair once and never replaces one.
sh = open(os.path.join(os.path.dirname(__file__), '..', 'deploy', 'install.sh')).read()
check('install.sh creates a VAPID pair when none is set',
      'if [ -z "$(_vapid_val VAPID_PRIVATE_KEY)" ] && [ -z "$(_vapid_val VAPID_PUBLIC_KEY)" ]' in sh
      and 'ec.generate_private_key(ec.SECP256R1())' in sh
      and "printf '\\nVAPID_PUBLIC_KEY=%s\\nVAPID_PRIVATE_KEY=%s\\n'" in sh)
check('...and a key-generation failure never aborts the deploy', ")\" || VAPID_PAIR=''" in sh)
check('...and an existing pair is left untouched', 'VAPID key pair present' in sh)
raise SystemExit(0 if all(checks) else 1)
