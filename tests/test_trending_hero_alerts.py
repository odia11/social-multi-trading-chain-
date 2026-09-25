"""When a token starts trending on the home feed, members are told.

- every member with notifications on gets an in-app notification, and
  those with a registered phone get a push, tagged 'orc-trending' so a newer
  one replaces the older one on the phone;
- tapping it opens the home feed scrolled to the card (/?trending=1#trending);
- once the card is on screen the app closes the phone notification and
  marks the in-app one read (POST /api/home/trending-hero/seen);
- it never becomes noise: a token is announced at most once per 12h, and at
  most one announcement per 30 minutes overall; members who turned
  notifications off get nothing.
"""
import json, os, re, sqlite3, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0'})
import app_entry  # noqa: E402
import trending_hero as th  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
ROOT = os.path.join(os.path.dirname(__file__), '..')

pushed = []
d._send_push_notifications_bulk = lambda ids, t, b, u='/', ic='', tag='': pushed.append((sorted(ids), t, b, u, ic, tag))

def member(notifs=True, phone=False):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = sqlite3.connect(d.DB_FILE)
    c.execute('UPDATE users SET pref_notifications=? WHERE id=?', (1 if notifs else 0, uid))
    if phone:
        c.execute('INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth) VALUES (?,?,?,?)',
                  (uid, 'https://push.example/' + w, 'k', 'a'))
    c.commit(); c.close()
    return w, uid
a_w, a = member(phone=True)
b_w, b = member()
c_w, c_off = member(notifs=False, phone=True)

def trending_notes(uid):
    c = sqlite3.connect(d.DB_FILE)
    rows = c.execute("SELECT content, link, is_read FROM notifications WHERE user_id=? AND type='trending' ORDER BY id",
                     (uid,)).fetchall()
    c.close(); return rows

WOJAK = {'mint': 'WojakMint1111111111111111111111111111111pump', 'symbol': 'wojak', 'chain': 'solana',
         'price_change_24h': 184.2, 'volume_24h': 482000, 'image_url': 'https://cdn.example/wojak.png'}
PEPE = dict(WOJAK, mint='PepeMint11111111111111111111111111111111pump', symbol='PEPE', image_url='http://x/y.png')

T0 = 1_800_000_000
n = th.announce(d, WOJAK, now=T0)
check('a new trending token notifies members in-app', n >= 2 and trending_notes(a) and trending_notes(b))
check('...with the ticker and the numbers', trending_notes(a)[-1][0] == '🔥 $WOJAK is trending · +184.2% · $482K volume · Solana')
check('...linking straight to the card on the home feed', trending_notes(a)[-1][1] == '/?trending=1#trending')
check('members who turned notifications off get nothing', not trending_notes(c_off))
check('a push goes to members with a phone registered (and notifications on)',
      len(pushed) == 1 and pushed[0][0] == [a])
check('...tagged so a newer alert replaces the older one', pushed[0][5] == 'orc-trending')
check('...with the token logo (https only) and the home-card link',
      pushed[0][4] == 'https://cdn.example/wojak.png' and pushed[0][3] == '/?trending=1#trending')

check('the same token is not announced again soon', th.announce(d, WOJAK, now=T0 + 3600) == 0)
check('a new token within 30 minutes of the last alert waits', th.announce(d, PEPE, now=T0 + 600) == 0)
check('after 30 minutes a new token is announced', th.announce(d, PEPE, now=T0 + 31 * 60) >= 2)
check('...an http logo is dropped (mixed content)', pushed[-1][4] == '')
check('...and the older unread trending alert is marked read', trending_notes(b)[0][2] == 1 and trending_notes(b)[-1][2] == 0)
check('the first token can be announced again after 12h', th.announce(d, WOJAK, now=T0 + 13 * 3600) >= 2)

# Seen: the card was on screen -> this member's trending alerts are read.
client = app.test_client()
with client.session_transaction(base_url='https://orcagent.fun') as s:
    s['wallet'] = b_w; s['user_id'] = b; s['csrf_token'] = 'tok' * 10
r = client.post('/api/home/trending-hero/seen', json={}, headers={'X-CSRF-Token': 'tok' * 10},
                base_url='https://orcagent.fun').get_json()
check('seeing the card marks my trending alert read', r['ok'] and all(row[2] == 1 for row in trending_notes(b)))
check('...and only mine', any(row[2] == 0 for row in trending_notes(a)))

# The phone side: the push payload carries the tag, the service worker uses it.
snd = re.search(r'def _send_push_notification_sync\(.*?\n(?=def )', open(os.path.join(ROOT, 'dashboard.py')).read(), re.S).group(0)
check('the push payload carries the tag', "'tag': tag" in snd)
sw = open(os.path.join(ROOT, 'static', 'sw.js')).read()
js = r'''
var listeners={}, shown=null;
var self={location:{origin:'https://orcagent.fun'},addEventListener:function(n,f){listeners[n]=f},
  registration:{showNotification:function(t,o){shown={title:t,opts:o};return Promise.resolve()}}};
var clients={matchAll:function(){return Promise.resolve([])},openWindow:function(){return Promise.resolve()}};
''' + sw + r'''
var p; listeners.push({data:{json:function(){return {title:'T',body:'B',url:'/?trending=1#trending',tag:'orc-trending'}}},waitUntil:function(x){p=x}});
p.then(function(){console.log(JSON.stringify(shown))});
'''
out = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=30).stdout.strip()
shown = json.loads(out) if out else {}
check('the service worker shows it with that tag (replacing older ones)',
      shown.get('opts', {}).get('tag') == 'orc-trending' and shown['opts'].get('renotify') is True)
check('...and keeps the home-card link for the tap', shown.get('opts', {}).get('data', {}).get('url') == '/?trending=1#trending')

# The app: arriving from the alert scrolls to the card; seeing it clears the alert.
hero_js = open(os.path.join(ROOT, 'static', 'home-trending-hero.js')).read()
check('arriving via the alert scrolls to the card', "location.hash==='#trending'" in hero_js and 'scrollTo' in hero_js)
check('once on screen it closes the phone notification',
      "getNotifications({tag:'orc-trending'})" in hero_js and 'n.close()' in hero_js)
check('...and marks the in-app alert read', "'/api/home/trending-hero/seen'" in hero_js)
raise SystemExit(0 if all(checks) else 1)
