"""The Messages inbox (chat list) is clean and easy to use.

- the red swipe-to-delete action no longer shows through the right edge of
  every chat card: it is only painted while a card is swiped open;
- each chat shows name, time, a one-line preview and an unread count;
  tips read as a tip ("You tipped 15.00 USDC" / "Tipped you …");
- the header says how many messages are unread, there are All / Unread
  filters, an "Active now" row of online chats, and a friendly empty state;
- the inbox stylesheet is served on /messages after the older bundle.
"""
import json, os, re, subprocess, sys, tempfile
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
CSS = open(os.path.join(ROOT, 'static', 'messages-inbox.css'), encoding='utf-8').read()

# ── the red edge ──
rule = lambda sel: (re.search(re.escape(sel) + r'\{([^}]*)\}', CSS) or [None, ''])[1]
check('the delete action is not painted at rest', 'visibility:hidden' in rule('#msgs-left .conv-delete-btn'))
check('...only while the card is swiped', 'visibility:visible' in rule('#msgs-left .conv-row-wrap.oa-swiping .conv-delete-btn'))
check('...and the card clips it to its rounded shape', 'overflow:hidden' in rule('#msgs-left .conv-row-wrap'))
check('the swipe code marks the card while it is moved',
      "wrapEl.classList.add('oa-swiping')" in HTML and "wrapEl.classList.remove('oa-swiping')" in HTML)
check('the card itself is opaque (nothing shows through)', 'background:var(--ib-card)!important' in rule('#msgs-left .conv-row'))
check('the old "›" chevron and slogan are gone',
      'content:none' in rule('#msgs-left .conv-row:after') and 'content:none' in rule('#msgs-left .msgs-left-title-row:after'))

# ── preview line (run the page's own function) ──
def js_fn(name):
    i = HTML.index('function ' + name + '(')
    depth, j = 0, HTML.index('{', i)
    for k in range(j, len(HTML)):
        depth += {'{': 1, '}': -1}.get(HTML[k], 0)
        if depth == 0:
            return HTML[i:k + 1]
tip_re = re.search(r'var _TIP_RE = [^\n]+', HTML).group(0)
cases = [
    {'last_is_mine': True, 'last_type': 'text', 'last_msg': 'Tipped 15.00 USDC — Tesla pump was insane'},
    {'last_is_mine': False, 'last_type': 'text', 'last_msg': 'Tipped 2.50 USDC — thanks for the call'},
    {'last_is_mine': True, 'last_type': 'text', 'last_msg': 'Hi mama'},
    {'last_is_mine': False, 'last_type': 'image', 'last_msg': ''},
    {'last_is_mine': True, 'last_type': 'trade', 'last_msg': 'x'},
    {'last_is_mine': False, 'last_type': 'text', 'last_msg': '<img src=x onerror=alert(1)>'},
]
script = (js_fn('_esc') + '\n' + tip_re + '\n' + js_fn('_convPreviewHtml') + '\n'
          + 'console.log(JSON.stringify(' + json.dumps(cases) + '.map(_convPreviewHtml)));')
out = json.loads(subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=30).stdout)
check('a tip you sent reads "You tipped 15.00 USDC" + the note',
      'oa-tip-chip sent' in out[0] and 'You tipped <b>15.00 USDC</b>' in out[0] and 'Tesla pump was insane' in out[0])
check('a tip you got reads "Tipped you 2.50 USDC" (green)', 'oa-tip-chip got' in out[1] and 'Tipped you <b>2.50 USDC</b>' in out[1])
check('your own text starts with "You:"', out[2] == '<span class="oa-you">You:</span> Hi mama')
check('photos and trades read as such', '📷 Photo' in out[3] and '📊 Shared a trade' in out[4] and 'You:' in out[4])
check('message text is escaped', '<img' not in out[5] and '&lt;img' in out[5])

# ── rows, header, filters, active now, empty state ──
check('each chat shows its unread count (not just a dot)', "'<span class=\"conv-badge\" aria-label=\"'+c.unread+' unread\">'" in HTML
      and 'min-width:22px' in rule('#msgs-left .conv-badge'))
check('unread chats are highlighted', "(unread ? ' is-unread' : '')" in HTML and rule('#msgs-left .conv-row-wrap.is-unread .conv-row'))
check('the header says how many are unread', "unreadMsgs + ' unread message'" in HTML and 'id="oa-inbox-sub"' in HTML)
check('All / Unread filters', 'data-filter="all"' in HTML and 'data-filter="unread"' in HTML
      and "c.unread > 0; })" in HTML and 'function _setConvFilter(' in HTML)
check('"Active now" row of online chats opens the chat', 'id="oa-active-strip"' in HTML
      and 'c.peer_online; }).slice(0, 12)' in HTML and "_openThread(id, c.peer_username || ''" in HTML)
check('a friendly empty state with a "Start a chat" button', 'No messages yet' in HTML and 'onclick="_openNewMessage()">Start a chat' in HTML)
check('search is visible on phones too', 'display:block!important' in rule('#msgs-left .msgs-search-wrap'))
check('inputs are 16px so iOS does not zoom', 'font-size:16px' in rule('#msgs-left .msgs-search') and 'font-size:16px' in rule('#msgs-left .new-msg-input'))

# ── served on the page ──
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
c = app.test_client()
with c.session_transaction(base_url='https://orcagent.fun') as s:
    s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = 'tok' * 10
page = c.get('/messages', base_url='https://orcagent.fun').get_data(as_text=True)
check('/messages loads the inbox stylesheet after the older bundle',
      'messages-inbox.css?v=1' in page and page.index('messages-ui.css') < page.index('messages-inbox.css'))
raise SystemExit(0 if all(checks) else 1)
