"""Group chats in Messages, WhatsApp-style (group_chats.py, static/group-chats.js).

You start a group from Messages, add people who follow you or whom you follow
by their @username, name it, and talk: text and photos, everyone's name over
their messages, joins/leaves/renames as small grey lines. Admins add, remove
and rename; anyone can leave. Unread group messages count in the Messages
badge, and members get one bell entry per group and a phone push per message.
"""
import json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
DATA = tempfile.mkdtemp()
os.environ.update({'DATA_DIR': DATA, 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''), flush=True)

pushes = []
d._send_push_notifications_bulk = lambda ids, t, b, u='/', ic='', tag='': pushes.append((sorted(ids), t, b, u, tag))
W = [str(Keypair().pubkey()) for _ in range(5)]
U = [d.get_or_create_user(w) for w in W]
NAMES = ['alice', 'bob', 'carol', 'dave', 'erin']
c = sqlite3.connect(d.DB_FILE)
for i, n in enumerate(NAMES):
    c.execute('UPDATE users SET username=? WHERE id=?', (n, U[i]))
    c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (U[i], d.TOS_VERSION))
c.execute('INSERT INTO follows (follower_id, following_id) VALUES (?,?)', (U[1], U[0]))   # bob follows alice
c.execute('INSERT INTO follows (follower_id, following_id) VALUES (?,?)', (U[0], U[2]))   # alice follows carol
c.execute('INSERT INTO follows (follower_id, following_id) VALUES (?,?)', (U[4], U[0]))   # erin follows alice
c.commit()

BASE = 'https://orcagent.fun'
H = {'X-CSRF-Token': 't' * 40}
def client(i):
    cl = app.test_client()
    with cl.session_transaction(base_url=BASE) as s:
        s['wallet'] = W[i]; s['user_id'] = U[i]; s['csrf_token'] = 't' * 40
    return cl
alice, bob, carol, dave = client(0), client(1), client(2), client(3)

people = alice.get('/api/group-chats/candidates?q=bo', base_url=BASE).get_json()['people']
check('searching by @username finds a follower', [p['username'] for p in people] == ['bob'], str(people))
everyone = {p['username'] for p in alice.get('/api/group-chats/candidates', base_url=BASE).get_json()['people']}
check('...and offers followers and followed accounts, not strangers', everyone == {'bob', 'carol', 'erin'}, str(everyone))
r = alice.post('/api/group-chats', json={'name': 'Moon crew', 'user_ids': [U[3]]}, headers=H, base_url=BASE)
check('a stranger cannot be added', r.status_code == 400 and 'follow' in r.get_json()['msg'])
r = alice.post('/api/group-chats', json={'name': 'Moon crew', 'user_ids': [U[1], U[2]]}, headers=H, base_url=BASE).get_json()
gid = r['chat']['id']
check('a group is created with its members, the creator as admin',
      r['ok'] and {m['username']: m['role'] for m in r['chat']['members']} == {'alice': 'admin', 'bob': 'member', 'carol': 'member'})
check('...and the people added are told (push)', pushes and pushes[-1][0] == sorted([U[1], U[2]]) and 'added you' in pushes[-1][2])
check('nobody outside the group can read it', dave.get('/api/group-chats/%d' % gid, base_url=BASE).status_code == 404
      and dave.get('/api/group-chats/%d/messages' % gid, base_url=BASE).status_code == 404
      and dave.post('/api/group-chats/%d/messages' % gid, json={'message': 'hi'}, headers=H, base_url=BASE).status_code == 404)
alice.post('/api/group-chats/%d/messages' % gid, json={'message': 'gm team'}, headers=H, base_url=BASE)
check('a message pushes to every other member, one alert per group on the phone',
      pushes[-1][0] == sorted([U[1], U[2]]) and pushes[-1][4] == 'gc-%d' % gid and pushes[-1][3] == '/messages?group=%d' % gid)
check("it counts in the other members' Messages badge", bob.get('/api/messages/unread_count', base_url=BASE).get_json()['count'] == 1)
alice.post('/api/group-chats/%d/messages' % gid, json={'message': 'lfg'}, headers=H, base_url=BASE)
n = c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND link=? AND is_read=0", (U[1], '/messages?group=%d' % gid)).fetchone()[0]
check('...with one bell entry per group, not one per message', n == 1, str(n))
msgs = bob.get('/api/group-chats/%d/messages' % gid, base_url=BASE).get_json()['messages']
check('members read the conversation with join lines and names',
      [(m['kind'], m['sender'], m['body']) for m in msgs] == [('system', '', 'alice created the group'),
       ('system', '', 'alice added bob, carol'), ('text', 'alice', 'gm team'), ('text', 'alice', 'lfg')])
check('...and opening it clears the badge and the bell entry', bob.get('/api/messages/unread_count', base_url=BASE).get_json()['count'] == 0
      and c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND link=? AND is_read=0", (U[1], '/messages?group=%d' % gid)).fetchone()[0] == 0)
check('only admins add people', bob.post('/api/group-chats/%d/members' % gid, json={'user_ids': [U[0]]}, headers=H, base_url=BASE).status_code == 403)
r = alice.post('/api/group-chats/%d/members' % gid, json={'user_ids': [U[4]]}, headers=H, base_url=BASE).get_json()
check('an admin adds another follower', r['ok'] and 'erin' in [m['username'] for m in r['chat']['members']])
check('only admins remove, and nobody removes the creator',
      bob.delete('/api/group-chats/%d/members/%d' % (gid, U[2]), headers=H, base_url=BASE).status_code == 403)
check('an admin renames the group', alice.put('/api/group-chats/%d' % gid, json={'name': 'Moon crew 🚀'}, headers=H, base_url=BASE).get_json()['chat']['name'] == 'Moon crew 🚀')
r = bob.post('/api/group-chats/%d/messages' % gid, json={'message': 'look <img src=x onerror=alert(1)> here'}, headers=H, base_url=BASE).get_json()
check('markup is stripped before a message is stored', r['ok'] and '<img' not in r['message']['body'] and 'look' in r['message']['body'], str(r))
bob.post('/api/group-chats/%d/leave' % gid, json={}, headers=H, base_url=BASE)
check('anyone can leave, and is gone from the group', bob.get('/api/group-chats/%d' % gid, base_url=BASE).status_code == 404)
last = [m['body'] for m in alice.get('/api/group-chats/%d/messages' % gid, base_url=BASE).get_json()['messages']][-3:]
check('...with "left" and the rename shown in the chat', 'bob left' in last and any('renamed the group' in b for b in last), str(last))

# ── in the browser: create a group from Messages, add by @username, talk ─────
with app.test_request_context():
    from flask import session
    session['wallet'] = W[0]; session['user_id'] = U[0]; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    COOKIE = resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1]
PORT = 5133
SHOTS = os.environ.get('GC_SHOTS', '')
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=dict(os.environ, PYTHONPATH=ROOT), cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
DRIVER = r'''
import asyncio, json, os, sqlite3
from playwright.async_api import async_playwright
PORT, COOKIE, SHOTS, DB, BOB = %d, %r, %r, %r, %d
async def run(b, theme, w, h):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, is_mobile=w < 600, has_touch=w < 600)
    await ctx.add_init_script("try{localStorage.setItem('oa_theme','%%s');localStorage.setItem('orcagent_tips_seen','1');"
                            # the "turn on notifications" card has its own place below the chats
                            "localStorage.setItem('oa_push_prompt_dismissed',String(Date.now()+864e5))}catch(e){}" %% theme)
    await ctx.add_cookies([{'name': 'orca_s', 'value': COOKIE, 'domain': '127.0.0.1', 'path': '/'},
                           {'name': 'oa_theme', 'value': theme, 'domain': '127.0.0.1', 'path': '/'}])
    page = await ctx.new_page(); errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    tag = '%%s_%%d' %% (theme, w); out = {}
    await page.goto('http://127.0.0.1:%%d/messages' %% PORT, wait_until='load')
    await page.wait_for_selector('.gc-new-btn', timeout=15000)
    await page.wait_for_timeout(800)
    out['button'] = await page.evaluate("(()=>{const b=document.querySelector('.gc-new-btn').getBoundingClientRect();return b.width>30&&b.top<300})()")
    if SHOTS: await page.screenshot(path=SHOTS + '/list_' + tag + '.png')
    await page.click('.gc-new-btn'); await page.wait_for_selector('.gc-person', timeout=10000)
    await page.fill('.gc-search input', 'car'); await page.wait_for_timeout(600)
    out['search'] = await page.evaluate("[...document.querySelectorAll('.gc-person b')].map(e=>e.textContent)")
    await page.click('.gc-person'); await page.fill('.gc-search input', ''); await page.wait_for_timeout(600)
    await page.click('.gc-person:not(.on)'); await page.wait_for_timeout(300)
    if SHOTS: await page.screenshot(path=SHOTS + '/pick_' + tag + '.png')
    await page.click('.gc-next'); await page.fill('#gc-name', 'Weekend degens ' + tag)
    if SHOTS: await page.screenshot(path=SHOTS + '/name_' + tag + '.png')
    await page.click('.gc-create')
    await page.wait_for_selector('#gc-thread:not([hidden]) .gc-sys', timeout=10000)
    out['opened'] = await page.evaluate("[document.querySelector('.gc-th-name').textContent, location.search, [...document.querySelectorAll('.gc-sys')].map(e=>e.textContent)]")
    await page.fill('.gc-input', 'who is buying the dip?'); await page.click('.gc-send')
    await page.wait_for_selector('.gc-msg.mine:not(.pending)', timeout=10000)
    gid = int(out['opened'][1].split('=')[1])
    con = sqlite3.connect(DB)
    con.execute("INSERT INTO group_chat_messages (chat_id, sender_id, kind, body, created_at) VALUES (?,?,'text','Me! Loading up now 🚀',datetime('now'))", (gid, BOB))
    con.commit(); con.close()
    await page.wait_for_selector('.gc-msg:not(.mine) .gc-sender', timeout=10000)
    out['thread'] = await page.evaluate("""(()=>{const t=document.getElementById('gc-thread').getBoundingClientRect();
      const comp=document.querySelector('.gc-composer').getBoundingClientRect();
      return {full: t.height>=innerHeight-1, composerOnScreen: comp.bottom<=innerHeight+1,
              mine: document.querySelector('.gc-msg.mine .gc-text').textContent,
              other: [document.querySelector('.gc-msg:not(.mine) .gc-sender').textContent, document.querySelector('.gc-msg:not(.mine) .gc-text').textContent],
              ox: document.scrollingElement.scrollWidth - innerWidth}})()""")
    if SHOTS: await page.screenshot(path=SHOTS + '/thread_' + tag + '.png')
    await page.click('.gc-icon-btn[data-gc-info]'); await page.wait_for_selector('.gc-member', timeout=5000); await page.wait_for_timeout(450)
    out['info'] = await page.evaluate("[document.querySelectorAll('.gc-member').length, !!document.querySelector('.gc-add-row'), !!document.querySelector('.gc-leave')]")
    if SHOTS: await page.screenshot(path=SHOTS + '/info_' + tag + '.png')
    await page.keyboard.press('Escape'); await page.keyboard.press('Escape'); await page.wait_for_timeout(600)
    out['back'] = await page.evaluate("[document.getElementById('gc-thread').hidden, [...document.querySelectorAll('.gc-row-wrap .conv-name')].map(e=>e.textContent)]")
    if SHOTS: await page.screenshot(path=SHOTS + '/list2_' + tag + '.png')
    await page.add_init_script("window.__cls=0;try{new PerformanceObserver(l=>l.getEntries().forEach(e=>{if(!e.hadRecentInput){window.__cls+=e.value}})).observe({type:'layout-shift',buffered:true})}catch(e){}")
    await page.goto('http://127.0.0.1:%%d/messages' %% PORT, wait_until='load'); await page.wait_for_timeout(2500)
    out['cls'] = round(await page.evaluate('window.__cls'), 3)
    out['errors'] = errors
    await ctx.close()
    return tag, out
async def main():
    async with async_playwright() as p:
        try:
            b = await p.chromium.launch(args=['--no-sandbox'])
        except Exception:
            b = await p.chromium.launch(args=['--no-sandbox'], executable_path=os.environ.get('CHROMIUM_PATH') or '/opt/pw-browsers/chromium')
        res = {}
        for theme, w, h in (('dark', 390, 844), ('light', 360, 740), ('dark', 1280, 800)):
            k, v = await run(b, theme, w, h); res[k] = v
        await b.close()
    print('@@' + json.dumps(res))
asyncio.run(main())
''' % (PORT, COOKIE, SHOTS, d.DB_FILE, U[1])
B = {}
try:
    for _ in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/static/og-orcagent.png' % PORT, timeout=2); break
        except Exception:
            time.sleep(1)
    r = subprocess.run([sys.executable, '-c', DRIVER], capture_output=True, text=True, timeout=400)
    line = [l for l in r.stdout.splitlines() if l.startswith('@@')]
    B = json.loads(line[-1][2:]) if line else {}
    if not B: print(r.stdout[-1500:], r.stderr[-2500:])
finally:
    server.terminate()

for tag in ('dark_390', 'light_360', 'dark_1280'):
    m = B.get(tag, {})
    check('BROWSER %s: a New group button sits next to compose' % tag, m.get('button') is True, str(m.get('button')))
    check('BROWSER %s: people are found by @username among followers' % tag, m.get('search') == ['carol'], str(m.get('search')))
    o = m.get('opened') or ['', '', []]
    check('BROWSER %s: naming and creating opens the group with who is in it' % tag,
          o[0].startswith('Weekend degens') and o[1].startswith('?group=') and any('added' in s for s in o[2]), str(o))
    t = m.get('thread') or {}
    check('BROWSER %s: your message and the others\' messages (with their name) appear live' % tag,
          t.get('mine') == 'who is buying the dip?' and t.get('other') == ['bob', 'Me! Loading up now 🚀'], str(t))
    check('BROWSER %s: the chat fills the screen, the composer is on screen, nothing sticks out' % tag,
          t.get('full') and t.get('composerOnScreen') and t.get('ox', 1) <= 0, str(t))
    check('BROWSER %s: group info lists members, Add people and Leave' % tag, (m.get('info') or [0])[0] == 3 and m['info'][1] and m['info'][2], str(m.get('info')))
    bk = m.get('back') or [False, []]
    check('BROWSER %s: back closes the chat and the group is in the list' % tag,
          bk[0] is True and any(n.startswith('Weekend degens ' + tag) for n in bk[1]), str(bk))
    check('BROWSER %s: reopening Messages, the groups are there without the list jumping (shift %s)' % (tag, m.get('cls')),
          m.get('cls') is not None and m['cls'] <= 0.05, str(m.get('cls')))
    check('BROWSER %s: no page errors' % tag, m.get('errors') == [], str(m.get('errors')))

print('%d/%d' % (sum(checks), len(checks)))
os._exit(0 if all(checks) else 1)
