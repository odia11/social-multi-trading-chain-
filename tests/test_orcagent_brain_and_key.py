"""@orcagent talks without an external AI service too, and the AI key can be
set from the Admin Console.

Without ANTHROPIC_API_KEY on the server every tag fell back to the canned
"Which OrcAgent feature is your question about?". Now:
- OrcAgent's own brain (orcagent_brain) answers in English and in character:
  crypto terms, jokes, roasts on request, thread summaries and reactions, a
  balanced never-advice token take, sums, the date, banter. Reviewed platform
  answers (how to connect a wallet...) and the deterministic live data,
  actions and privacy refusals stay as they are.
- An admin can paste an Anthropic key on Admin -> Platform assistant. It is
  checked against the API, stored encrypted, never shown again (last four
  characters only), and takes effect at once for every AI feature. A key the
  API rejects is not stored; a key in the server environment always wins.
"""
import os, re, sqlite3, sys, tempfile, time
from solders.keypair import Keypair
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
ADMIN = str(Keypair().pubkey())
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0', 'OWNER_WALLET': ADMIN})
os.environ.pop('ANTHROPIC_API_KEY', None)
import app_entry  # noqa: E402
d = app_entry._dashboard
import orcagent_brain as brain  # noqa: E402
import orcagent_chat as chat  # noqa: E402
import ai_key_admin  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

thread = [('post', 'maria', 'Just aped into $POPCAT, chart is pumping, lfg'), ('reply', 'bob', 'careful, it might rug')]
ans = lambda q, topic='scope': (brain.reply(q, 'bob', thread, (topic, 'x')) or (None, None))
check('explains crypto and trading terms', 'gap between the price you expected' in ans('what is slippage')[1]
      and 'bonding curve' in ans('explain a bonding curve')[1].lower() and 'HODL' in ans('hodl')[1])
check('jokes, a roast when asked, banter', ans('tell me a joke')[1] in brain.JOKES
      and ans('roast me')[1].endswith('(You asked.)') and ans('gm')[1].startswith('gm'))
check('summarises the public thread', ans('summarize this thread')[1].startswith('TL;DR: @maria posted')
      and '$POPCAT' in ans('tl;dr')[1])
check('reacts to the thread and gives a token take, never advice to buy',
      '$POPCAT' in ans('what do you think about this play?')[1]
      and 'Not financial advice.' in ans('is $WIF a good buy?')[1] and 'you should buy' not in ans('should I buy $WIF?')[1].lower())
check('does sums and knows the date', ans('12*7+3')[1].startswith('12*7+3 = 87')
      and ans('what day is it')[1].startswith("It's ") and brain._calc('2**999') is None and brain._calc('__import__("os")') is None)
check('an honest in-character answer instead of "Which OrcAgent feature…" (still labelled scope for learning)',
      ans('what is the meaning of life')[0] == 'scope' and 'Which OrcAgent feature' not in ans('what is the meaning of life')[1])
check('a reviewed platform answer stays (how to connect a wallet)', brain.reply('how do I connect my wallet', 'bob', [], ('wallet', 'x')) is None)
check('always English', all(not chat.looks_dutch(t) for t in list(brain.GLOSSARY.values()) + list(brain.JOKES) + list(brain.ROASTS)))

# ── end to end, no API key ──
def user(name, verified=0):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    with sqlite3.connect(d.DB_FILE) as c:
        c.execute('UPDATE users SET username=?, is_verified=? WHERE id=?', (name, verified, uid))
    return w, uid
_, agent = user('orcagent', 1)
bob_w, bob = user('bob')
maria_w, _ = user('maria')
d.get_or_create_user(ADMIN)
with sqlite3.connect(d.DB_FILE) as c:
    c.execute('INSERT INTO feed_posts (wallet, content) VALUES (?,?)', (maria_w, 'Just aped into $POPCAT lfg'))
    pid = c.execute('SELECT MAX(id) FROM feed_posts').fetchone()[0]
BASE, CSRF = 'https://orcagent.fun', 'c' * 40
def client(wallet):
    cl = app_entry.app.test_client()
    with cl.session_transaction(base_url=BASE) as s:
        s['wallet'] = wallet; s['csrf_token'] = CSRF
    return cl
bobc = client(bob_w)
def say(text):
    r = bobc.post('/api/feed/reply', json={'post_id': 'p%d' % pid, 'message': text}, headers={'X-CSRF-Token': CSRF}, base_url=BASE).get_json() or {}
    with sqlite3.connect(d.DB_FILE) as c:
        row = c.execute('SELECT message FROM feed_replies WHERE user_id=? AND parent_reply_id=?', (agent, r.get('id'))).fetchone()
    return r, row[0] if row else None
check('no API key: the model layer is off', not chat.available(d))
r, text = say('@orcagent what is slippage?')
check('...yet a tag gets OrcAgent\'s own answer at once', r.get('platform_reply_id') and text and 'gap between the price' in text)
r, text = say('@orcagent how much does @maria hold?')
check('...and the privacy refusal still wins', text == chat.PRIVACY_REFUSAL)
r, text = say('what is slippage?')
check('...and a message not addressed to OrcAgent gets no reply', text is None and not r.get('platform_reply_id'))

# ── the key, from the Admin Console ──
admin = client(ADMIN)
KEY = 'sk-ant-api03-' + 'A1b2C3d4E5f6' * 4 + 'wxyz'
check('only admins can see or set the key', bobc.get('/api/admin/platform-assistant/ai-key', base_url=BASE).status_code == 403
      and bobc.post('/api/admin/platform-assistant/ai-key', json={'key': KEY}, headers={'X-CSRF-Token': CSRF}, base_url=BASE).status_code == 403)
post = lambda body, headers={'X-CSRF-Token': CSRF}: admin.post('/api/admin/platform-assistant/ai-key', json=body, headers=headers, base_url=BASE)
check('...with a CSRF token', post({'key': KEY}, {}).status_code == 403)
check('something that is not an Anthropic key is refused', post({'key': 'hello'}).status_code == 400)
class R:
    def __init__(self, code): self.status_code = code
answer = {'code': 401}
d.requests.post = lambda *a, **k: R(answer['code'])
r = post({'key': KEY})
with sqlite3.connect(d.DB_FILE) as c:
    stored = c.execute("SELECT value FROM server_config WHERE key='anthropic_api_key_enc'").fetchone()
check('a key the API rejects is not saved', r.status_code == 400 and stored is None and not d.ANTHROPIC_API_KEY)
answer['code'] = 200
r = post({'key': KEY}); body = r.get_json() or {}
with sqlite3.connect(d.DB_FILE) as c:
    stored = c.execute("SELECT value FROM server_config WHERE key='anthropic_api_key_enc'").fetchone()
check('a valid key is saved encrypted, never in plain text', r.status_code == 200 and stored and KEY not in stored[0]
      and d._fernet.decrypt(stored[0].encode()).decode() == KEY)
check('...takes effect at once for every AI feature', d.ANTHROPIC_API_KEY == KEY and chat.available(d) and d._anthropic_operationally_available())
status = admin.get('/api/admin/platform-assistant/ai-key', base_url=BASE).get_data(as_text=True)
shown = admin.get('/api/admin/platform-assistant/ai-key', base_url=BASE).get_json()
check('...and is never shown again: only its last four characters', KEY not in status and shown.get('hint') == '…wxyz'
      and KEY not in r.get_data(as_text=True))
page = admin.get('/admin/platform-assistant', base_url=BASE).get_data(as_text=True)
check('the admin page shows the connection and the key form (password field)', 'Connected · key …wxyz' in page
      and 'type="password" name="key"' in page and KEY not in page)
d.ANTHROPIC_API_KEY = ''; ai_key_admin._state['source'] = None
ai_key_admin.load(d)
check('after a restart the stored key is loaded', d.ANTHROPIC_API_KEY == KEY)
r = admin.delete('/api/admin/platform-assistant/ai-key', headers={'X-CSRF-Token': CSRF}, base_url=BASE)
check('the key can be removed again', r.status_code == 200 and not d.ANTHROPIC_API_KEY and not chat.available(d))
d.ANTHROPIC_API_KEY = 'sk-ant-env-' + 'Z' * 30; ai_key_admin.load(d)
post({'key': KEY})
check('a key in the server environment always wins over a stored one', d.ANTHROPIC_API_KEY.startswith('sk-ant-env-')
      and ai_key_admin.status(d)['source'] == 'environment')
raise SystemExit(0 if all(checks) else 1)
