"""@orcagent can feature someone else's call in its own post, with the live call card.

"New call from @trader: $TOKEN ..." carries that trader's call card, without
the "CALLED" badge (OrcAgent did not make the call). Every other account
still only shows a call card for a call that belongs to that very post: a
__CALL__ marker copied into someone else's post shows nothing.
"""
import json, os, sqlite3, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
import app_entry  # noqa: E402
import platform_assistant  # noqa: E402
from solders.keypair import Keypair  # noqa: E402
d = app_entry._dashboard
app = app_entry.app

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

trader, other, me, agent = (str(Keypair().pubkey()) for _ in range(4))
tid, oid, mid = (d.get_or_create_user(w) for w in (trader, other, me))
c = sqlite3.connect(d.DB_FILE)
c.execute("INSERT INTO users (wallet_address, username, is_verified) VALUES (?, 'orcagent', 1)", (agent,))
c.execute("UPDATE users SET username='chartwizard' WHERE id=?", (tid,))
c.commit()
platform_assistant.initialize(d.DB_FILE)
with sqlite3.connect(d.DB_FILE) as cc:
    cc.execute('BEGIN IMMEDIATE'); platform_assistant.identity(cc)   # pins the official author
marker = '__CALL__' + json.dumps({'id': 1})
own = c.execute("INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,datetime('now','-3 minutes'))",
                (trader, 'Calling it here.\n' + marker)).lastrowid
c.execute("INSERT INTO token_calls (id, user_id, wallet, mint, symbol, token_name, price_at_call, mcap_at_call, peak_price, "
          "chain, last_price, post_id) VALUES (1,?,?,?,?,?,?,?,?,?,?,?)",
          (tid, trader, 'MintPopcat1111111111111111111111111111111', 'POPCAT', 'Popcat', 0.0001, 141e6, 0.000157, 'solana', 0.00015, own))
featured = c.execute("INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,datetime('now','-2 minutes'))",
                     (agent, 'New call from @chartwizard: $POPCAT at a $141M market cap.\n' + marker)).lastrowid
copied = c.execute("INSERT INTO feed_posts (wallet, content, created_at) VALUES (?,?,datetime('now','-1 minutes'))",
                   (other, 'Look at this\n' + marker)).lastrowid
c.commit(); c.close()

client = app.test_client(); BASE = 'https://orcagent.fun'
with client.session_transaction(base_url=BASE) as s:
    s['wallet'] = me; s['user_id'] = mid; s['csrf_token'] = 'x' * 30
feed = client.get('/api/social/feed?filter=all&kinds=posts&limit=40', base_url=BASE).get_json() or {}
items = {i.get('id'): i for i in feed.get('items', []) if i.get('id')}

check('the trader\'s own call post shows its call card, as the caller',
      (items.get(own) or {}).get('call', {}).get('id') == 1 and not items[own]['call'].get('featured'))
check('@orcagent\'s post featuring that call shows the same live card',
      (items.get(featured) or {}).get('call', {}).get('id') == 1
      and abs(items[featured]['call']['multiplier'] - 1.57) < 0.001)
check('...marked as featured, so the card carries no "CALLED" badge for OrcAgent',
      items.get(featured, {}).get('call', {}).get('featured') is True)
check('a marker copied into anyone else\'s post still shows nothing',
      copied in items and 'call' not in items[copied])
JS = open(os.path.join(ROOT, 'static', 'dashboard.js'), encoding='utf-8').read()
check('the feed hides the CALLED badge on a featured call',
      "callHtml && !(e.call && e.call.featured) ? '<span class=\"fc-call-badge\">CALLED</span>'" in JS)

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
