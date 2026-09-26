"""The open chat: tips cannot be edited, and the chat fits the screen.

- a tip message ("Tipped 15.00 USDC — note") offers Delete only, never Edit;
  the server refuses to edit a tip, or to edit a message INTO a tip;
- tips show as a tip ("You tipped 15.00 USDC" / "Tipped you …");
- nothing sticks out past the side of the chat and it cannot be panned
  sideways: shared-trade cards are sized from the row, not from vw;
- the message menu opens under the bubble, fully on screen;
- editing shows clear Cancel / Save buttons;
- deleting (or editing) your own message works: the ownership check looked
  DM ids up in the legacy `messages` table and refused them.
"""
import json, os, re, sqlite3, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

ROOT = os.path.join(os.path.dirname(__file__), '..')
HTML = open(os.path.join(ROOT, 'templates', 'messages.html'), encoding='utf-8').read()
CSS = open(os.path.join(ROOT, 'static', 'messages-thread.css'), encoding='utf-8').read()

# ── the page's own functions, run in node ──
def js_fn(name):
    i = HTML.index('function ' + name + '(')
    depth, j = 0, HTML.index('{', i)
    for k in range(j, len(HTML)):
        depth += {'{': 1, '}': -1}.get(HTML[k], 0)
        if depth == 0:
            return HTML[i:k + 1]
tip_re = re.search(r'var _TIP_RE = [^\n]+', HTML).group(0)
script = '\n'.join([js_fn('_esc'), tip_re, js_fn('_isTipText'), js_fn('_tipBubbleHtml')]) + """
console.log(JSON.stringify([
  _isTipText('Tipped 15.00 USDC — Tesla pump'), _isTipText('Tipped 0.03 USDC'), _isTipText('hello'),
  _isTipText('I tipped 5 USDC'), _tipBubbleHtml('Tipped 15.00 USDC — Tesla <b>pump</b>', true),
  _tipBubbleHtml('Tipped 2.50 USDG — thanks', false)]));"""
out = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30).stdout)
check('tip messages are recognised', out[0] and out[1] and not out[2] and not out[3])
check('a tip you sent reads "You tipped 15.00 USDC" with the note, escaped',
      'msg-bubble msg-tip' in out[4] and 'You tipped <b>15.00 USDC</b>' in out[4]
      and 'Tesla &lt;b&gt;pump&lt;/b&gt;' in out[4])
check('a tip you got reads "Tipped you 2.50 USDG"', 'Tipped you <b>2.50 USDG</b>' in out[5])

check('the message menu offers Edit only for non-tip text',
      "var canEdit = m.message_type === 'text' && !_isTipText(m.message);" in HTML
      and "(canEdit ? '<button onclick=\"_startEditMsg('+m.id+')\">Edit</button>' : '')" in HTML)
check('...and Delete for every own message', "'<button class=\"danger\" onclick=\"_deleteMsg('+m.id+')\">Delete</button></div>'" in HTML)
check('editing a tip is refused in the page too', "if (_isTipText(currentText) || bubble.classList.contains('msg-tip')) return;" in HTML)

# ── the server ──
BASE, CSRF = 'https://orcagent.fun', 'tok' * 10
H = {'X-CSRF-Token': CSRF, 'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)'}
def member(name):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    c = sqlite3.connect(d.DB_FILE); c.execute('UPDATE users SET username=? WHERE id=?', (name, uid)); c.commit(); c.close()
    cl = app.test_client()
    with cl.session_transaction(base_url=BASE) as s:
        s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF
    return uid, cl
me, A = member('alice'); peer, _B = member('bob')
c = sqlite3.connect(d.DB_FILE)
tip_id = c.execute("INSERT INTO direct_messages (sender_id, receiver_id, message, message_type) VALUES (?,?,?, 'text')",
                   (me, peer, 'Tipped 15.00 USDC — for the call')).lastrowid
text_id = c.execute("INSERT INTO direct_messages (sender_id, receiver_id, message, message_type) VALUES (?,?,?, 'text')",
                    (me, peer, 'gm')).lastrowid
c.commit(); c.close()
put = lambda mid, msg: A.put(f'/api/messages/{mid}', json={'message': msg}, headers=H, base_url=BASE)
r = put(tip_id, 'Tipped 150.00 USDC — for the call')
check('the server refuses to edit a tip', r.status_code == 400 and 'cannot be edited' in r.get_json()['msg'])
r = put(text_id, 'Tipped 999.00 USDC — fake')
check('...or to turn a message into a fake tip', r.status_code == 400)
r = put(text_id, 'gm gm')
check('ordinary messages can still be edited', r.status_code == 200 and r.get_json()['ok'])
r = _B.delete(f'/api/messages/{text_id}', headers=H, base_url=BASE)
check("someone else cannot delete your message", r.status_code == 403)
r = A.delete(f'/api/messages/{tip_id}', headers=H, base_url=BASE)
# This used to be refused: the ownership check looked the DM id up in the
# legacy `messages` table instead of direct_messages.
check('a tip can be deleted by its sender', r.status_code == 200 and r.get_json()['ok'])

# ── fits the screen ──
rule = lambda sel: (re.search(re.escape(sel) + r'\{([^}]*)\}', CSS) or [None, ''])[1]
check('the chat cannot be panned sideways', 'overflow-x:hidden' in rule('#msgs-area') and 'touch-action:pan-y' in rule('#msgs-area'))
check('shared-trade cards are sized from the row, never wider',
      'width:min(520px,100%)' in rule('#msgs-area .msg-bubble-wrap:has(> .msg-trade)')
      and 'max-width:100%' in rule('#msgs-area .msg-bubble.msg-trade'))
check('rows and bubbles never exceed the chat width',
      'max-width:100%' in rule('#msgs-area .msg-wrap') and 'max-width:min(560px,100%)' in rule('#msgs-area .msg-bubble:not(.msg-trade):not(.msg-image)'))
check('the menu opens under the bubble on its own side (on screen)',
      'right:0' in rule('#msgs-area .msg-wrap.mine .msg-menu') and 'left:auto' in rule('#msgs-area .msg-wrap.mine .msg-menu'))
check('editing has readable Cancel / Save', 'msg-edit-cancel' in HTML and 'msg-edit-save' in HTML
      and 'background:#f7b955' in rule('#msgs-area .msg-edit-save'))

page = A.get('/messages', headers=H, base_url=BASE).get_data(as_text=True)
check('/messages loads the chat stylesheet last',
      'messages-thread.css?v=1' in page and page.index('messages-ui.css') < page.index('messages-thread.css'))
raise SystemExit(0 if all(checks) else 1)
