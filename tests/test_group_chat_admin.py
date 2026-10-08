"""Running a group chat (group_chats.py, static/group-chats.js).

Whoever starts a group owns it. The owner makes members admins (and takes it
back) and can delete the group for everyone. Admins rename the group, change
its photo and add or remove members -- but not other admins or the owner.
When the owner leaves, an admin (or the longest-standing member) takes over.
"""
import base64, io, json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
DATA = tempfile.mkdtemp()
os.environ.update({'DATA_DIR': DATA, 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402
from PIL import Image  # noqa: E402

checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''), flush=True)

d._send_push_notifications_bulk = lambda *a, **k: None
W = [str(Keypair().pubkey()) for _ in range(5)]
U = [d.get_or_create_user(w) for w in W]
c = sqlite3.connect(d.DB_FILE)
for i, n in enumerate(['alice', 'bob', 'carol', 'dave', 'erin']):
    c.execute('UPDATE users SET username=? WHERE id=?', (n, U[i]))
    c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (U[i], d.TOS_VERSION))
for a, b in ((1, 0), (0, 2), (4, 0)):   # bob, erin follow alice; alice follows carol
    c.execute('INSERT INTO follows (follower_id, following_id) VALUES (?,?)', (U[a], U[b]))
c.commit()

BASE = 'https://orcagent.fun'
H = {'X-CSRF-Token': 't' * 40}
def client(i):
    cl = app.test_client()
    with cl.session_transaction(base_url=BASE) as s:
        s['wallet'] = W[i]; s['user_id'] = U[i]; s['csrf_token'] = 't' * 40
    return cl
alice, bob, carol, dave, erin = (client(i) for i in range(5))
def png(color):
    buf = io.BytesIO(); Image.new('RGB', (900, 600), color).save(buf, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
def lines(cl, gid):
    return [m['body'] for m in cl.get('/api/group-chats/%d/messages' % gid, base_url=BASE).get_json()['messages'] if m['kind'] == 'system']

gid = alice.post('/api/group-chats', json={'name': 'Moon crew', 'user_ids': [U[1], U[2], U[4]]}, headers=H, base_url=BASE).get_json()['chat']['id']
info = alice.get('/api/group-chats/%d' % gid, base_url=BASE).get_json()['chat']
check('whoever starts the group owns it', info['is_owner'] and [m['username'] for m in info['members'] if m['owner']] == ['alice'])
check('a member cannot change the photo', bob.put('/api/group-chats/%d/photo' % gid, json={'photo': png('red')}, headers=H, base_url=BASE).status_code == 403)
check('a member cannot choose admins', bob.put('/api/group-chats/%d/members/%d' % (gid, U[2]), json={'role': 'admin'}, headers=H, base_url=BASE).status_code == 403)
check('a member cannot delete the group', bob.delete('/api/group-chats/%d' % gid, headers=H, base_url=BASE).status_code == 403)

r = alice.put('/api/group-chats/%d/members/%d' % (gid, U[1]), json={'role': 'admin'}, headers=H, base_url=BASE).get_json()
check('the owner makes a member an admin', r['ok'] and {m['username']: m['role'] for m in r['chat']['members']}['bob'] == 'admin')
check('...and the chat says so', 'alice made bob an admin' in lines(bob, gid))
check('an admin who is not the owner cannot choose admins',
      bob.put('/api/group-chats/%d/members/%d' % (gid, U[2]), json={'role': 'admin'}, headers=H, base_url=BASE).status_code == 403)

r = bob.put('/api/group-chats/%d/photo' % gid, json={'photo': png('#e84393')}, headers=H, base_url=BASE).get_json()
check('an admin changes the group photo', r['ok'] and r['chat']['photo'].startswith('/api/group-chats/%d/photo?v=' % gid), str(r)[:200])
listed = [x for x in carol.get('/api/group-chats', base_url=BASE).get_json()['chats'] if x['id'] == gid][0]
check('every member sees the new photo in their list', listed['photo'] == r['chat']['photo'])
ph = carol.get(r['chat']['photo'], base_url=BASE)
check('members load the photo, small and never cached for others', ph.status_code == 200 and ph.mimetype.startswith('image/')
      and len(ph.data) < 200 * 1024 and 'private' in ph.headers.get('Cache-Control', ''),
      '%s %s %d' % (ph.status_code, ph.headers.get('Cache-Control'), len(ph.data)))
check('...and squared down to an avatar size', max(Image.open(io.BytesIO(ph.data)).size) <= 512, str(Image.open(io.BytesIO(ph.data)).size))
check('people outside the group cannot load it', dave.get(r['chat']['photo'], base_url=BASE).status_code == 404)
check('...and "changed the group photo" shows in the chat', 'bob changed the group photo' in lines(carol, gid))
check('only photos are accepted', bob.put('/api/group-chats/%d/photo' % gid, json={'photo': 'data:text/html;base64,PGI+'}, headers=H, base_url=BASE).status_code == 400)

check('an admin removes a member', bob.delete('/api/group-chats/%d/members/%d' % (gid, U[4]), headers=H, base_url=BASE).get_json()['ok'])
check('...but not the owner', bob.delete('/api/group-chats/%d/members/%d' % (gid, U[0]), headers=H, base_url=BASE).status_code == 403)
alice.put('/api/group-chats/%d/members/%d' % (gid, U[2]), json={'role': 'admin'}, headers=H, base_url=BASE)
check('...and not another admin', bob.delete('/api/group-chats/%d/members/%d' % (gid, U[2]), headers=H, base_url=BASE).status_code == 403)
r = alice.put('/api/group-chats/%d/members/%d' % (gid, U[2]), json={'role': 'member'}, headers=H, base_url=BASE).get_json()
check('the owner takes admin back', {m['username']: m['role'] for m in r['chat']['members']}['carol'] == 'member'
      and 'alice removed carol as admin' in lines(alice, gid))
check('carol, a member again, cannot rename', carol.put('/api/group-chats/%d' % gid, json={'name': 'x'}, headers=H, base_url=BASE).status_code == 403)
r = bob.delete('/api/group-chats/%d/photo' % gid, headers=H, base_url=BASE).get_json()
check('an admin removes the photo', r['ok'] and r['chat']['photo'] == '')

check('an admin cannot delete the group', bob.delete('/api/group-chats/%d' % gid, headers=H, base_url=BASE).status_code == 403)
alice.post('/api/group-chats/%d/messages' % gid, json={'message': 'bye'}, headers=H, base_url=BASE)
check('the owner deletes the group', alice.delete('/api/group-chats/%d' % gid, headers=H, base_url=BASE).get_json()['ok'])
check('...it is gone for everyone', all(cl.get('/api/group-chats/%d' % gid, base_url=BASE).status_code == 404 for cl in (alice, bob, carol))
      and c.execute('SELECT COUNT(*) FROM group_chat_messages WHERE chat_id=?', (gid,)).fetchone()[0] == 0
      and c.execute('SELECT COUNT(*) FROM group_chats WHERE id=?', (gid,)).fetchone()[0] == 0)
note = c.execute("SELECT content, link FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 1", (U[1],)).fetchone()
check('...and the members are told who deleted it', note == ('alice deleted the group "Moon crew"', '/messages'), str(note))
check('...without leftover bell entries that open it', c.execute('SELECT COUNT(*) FROM notifications WHERE link=?',
                                                                 ('/messages?group=%d' % gid,)).fetchone()[0] == 0)

g2 = alice.post('/api/group-chats', json={'name': 'Degens', 'user_ids': [U[1], U[2]]}, headers=H, base_url=BASE).get_json()['chat']['id']
alice.put('/api/group-chats/%d/members/%d' % (g2, U[2]), json={'role': 'admin'}, headers=H, base_url=BASE)
alice.post('/api/group-chats/%d/leave' % g2, json={}, headers=H, base_url=BASE)
info = carol.get('/api/group-chats/%d' % g2, base_url=BASE).get_json()['chat']
check('when the owner leaves, an admin takes over the group', info['is_owner'] and 'carol now owns the group' in lines(carol, g2), str(info)[:200])
check('...who can then delete it', carol.delete('/api/group-chats/%d' % g2, headers=H, base_url=BASE).get_json()['ok'])

# ── in the browser: the owner changes the photo, makes an admin, sees Delete ──
gid = alice.post('/api/group-chats', json={'name': 'Beta testers', 'user_ids': [U[1], U[2], U[4]]}, headers=H, base_url=BASE).get_json()['chat']['id']
with app.test_request_context():
    from flask import session
    session['wallet'] = W[0]; session['user_id'] = U[0]; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    COOKIE = resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1]
PHOTO = os.path.join(DATA, 'group.jpg')
Image.new('RGB', (800, 500), '#6c5ce7').save(PHOTO, 'JPEG')
PORT = 5134
SHOTS = os.environ.get('GC_SHOTS', '')
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=dict(os.environ, PYTHONPATH=ROOT), cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
DRIVER = r'''
import asyncio, json, os
from playwright.async_api import async_playwright
PORT, COOKIE, SHOTS, GID, PHOTO = %d, %r, %r, %d, %r
async def run(b, theme, w, h):
    ctx = await b.new_context(viewport={'width': w, 'height': h}, is_mobile=w < 600, has_touch=w < 600)
    await ctx.add_init_script("try{localStorage.setItem('oa_theme','%%s');localStorage.setItem('orcagent_tips_seen','1')}catch(e){}" %% theme)
    await ctx.add_cookies([{'name': 'orca_s', 'value': COOKIE, 'domain': '127.0.0.1', 'path': '/'},
                           {'name': 'oa_theme', 'value': theme, 'domain': '127.0.0.1', 'path': '/'}])
    page = await ctx.new_page(); errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('dialog', lambda dlg: asyncio.ensure_future(dlg.accept()))
    tag = '%%s_%%d' %% (theme, w); out = {}
    await page.goto('http://127.0.0.1:%%d/messages?group=%%d' %% (PORT, GID), wait_until='load')
    await page.wait_for_selector('#gc-thread:not([hidden]) .gc-sys', timeout=15000)
    await page.click('.gc-emoji'); await page.wait_for_selector('.gc-emoji-panel:not([hidden])', timeout=5000)
    out['emojiPanel'] = await page.evaluate("(()=>{const r=document.querySelector('.gc-emoji-panel').getBoundingClientRect();"
                                            "return [document.querySelectorAll('.gc-emoji-panel button').length, r.left>=0&&r.right<=innerWidth&&r.top>=0]})()")
    if SHOTS: await page.screenshot(path=SHOTS + '/emoji_' + tag + '.png')
    await page.fill('.gc-input', 'to the moon ')
    await page.click('.gc-emoji-panel button[aria-label=\"🚀\"]'); await page.click('.gc-emoji-panel button[aria-label=\"💎\"]')
    out['emojiInput'] = await page.evaluate("document.querySelector('.gc-input').value")
    await page.click('.gc-send'); await page.wait_for_selector('.gc-msg.mine:not(.pending)', timeout=10000)
    out['emojiSent'] = await page.evaluate("[[...document.querySelectorAll('.gc-msg.mine .gc-text')].pop().textContent, document.querySelector('.gc-emoji-panel').hidden]")
    await page.click('.gc-icon-btn[data-gc-info]'); await page.wait_for_selector('.gc-member', timeout=5000); await page.wait_for_timeout(450)
    out['owner'] = await page.evaluate("""[!!document.querySelector('.gc-info-photo .gc-info-cam'), !!document.querySelector('.gc-delete'),
        document.querySelectorAll('.gc-more').length, [...document.querySelectorAll('.gc-member small')].map(e=>e.textContent)[0],
        document.querySelector('.gc-sheet').getBoundingClientRect().right <= innerWidth + 1]""")
    if SHOTS: await page.screenshot(path=SHOTS + '/admin_info_' + tag + '.png')
    await page.set_input_files('.gc-photo-file', PHOTO)
    for _ in range(50):
        if await page.evaluate("(()=>{const i=document.querySelector('.gc-th-av img'),l=[...document.querySelectorAll('.gc-sys')].pop();"
                               "return !!(i&&i.complete&&i.naturalWidth>0&&l&&l.textContent.indexOf('photo')>0)})()"): break
        await page.wait_for_timeout(200)
    await page.wait_for_timeout(500)
    out['photo'] = await page.evaluate("[document.querySelector('.gc-th-av img').getAttribute('src'), !!document.querySelector('.gc-info-av img'), [...document.querySelectorAll('.gc-sys')].map(e=>e.textContent).slice(-1)[0]]")
    who = {'dark_390': 'bob', 'light_360': 'carol', 'dark_1280': 'erin'}[tag]
    await page.click('.gc-more[aria-label*=\"%%s\"]' %% who); await page.wait_for_selector('.gc-menu', timeout=5000); await page.wait_for_timeout(350)
    out['menu'] = await page.evaluate("[...document.querySelectorAll('.gc-menu > *')].map(e=>e.firstChild.textContent.trim())")
    if SHOTS: await page.screenshot(path=SHOTS + '/admin_menu_' + tag + '.png')
    await page.click('[data-act=admin]'); await page.wait_for_selector('.gc-sheet-info', timeout=5000); await page.wait_for_timeout(400)
    out['made'] = await page.evaluate("[...document.querySelectorAll('.gc-member')].filter(e=>e.textContent.indexOf('%%s')>=0).map(e=>e.querySelector('small').textContent)" %% who)
    if SHOTS: await page.screenshot(path=SHOTS + '/admin_after_' + tag + '.png')
    await page.keyboard.press('Escape'); await page.wait_for_timeout(200); await page.keyboard.press('Escape'); await page.wait_for_timeout(500)
    out['listPhoto'] = await page.evaluate("(()=>{const r=document.querySelector('.gc-row-wrap[data-gc=\"%%d\"] .gc-avatar img');return !!(r&&r.getAttribute('src').indexOf('/photo?v=')>0)})()" %% GID)
    if SHOTS: await page.screenshot(path=SHOTS + '/admin_list_' + tag + '.png')
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
''' % (PORT, COOKIE, SHOTS, gid, PHOTO)
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

for i, tag in enumerate(('dark_390', 'light_360', 'dark_1280')):
    m = B.get(tag, {})
    check('BROWSER %s: the composer has an emoji panel like DMs, fully on screen' % tag, m.get('emojiPanel') == [35, True], str(m.get('emojiPanel')))
    check('BROWSER %s: tapping emojis types them into the message' % tag, m.get('emojiInput') == 'to the moon 🚀💎', str(m.get('emojiInput')))
    check('BROWSER %s: ...and they are sent, the panel closes' % tag, m.get('emojiSent') == ['to the moon 🚀💎', True], str(m.get('emojiSent')))
    o = m.get('owner') or [False, False, 0, '', False]
    check('BROWSER %s: the owner sees a camera on the photo, Delete group, and options per member' % tag,
          o[0] and o[1] and o[2] == 3 and o[3] == 'Group owner' and o[4], str(o))
    p = m.get('photo') or ['', False, '']
    check('BROWSER %s: picking a photo puts it on the group at once' % tag,
          '/photo?v=' in (p[0] or '') and p[1] and 'changed the group photo' in (p[2] or ''), str(p))
    check('BROWSER %s: a member\'s options offer Make group admin and Remove' % tag,
          (m.get('menu') or [])[:1] == ['Make group admin'] and 'Remove from group' in (m.get('menu') or []), str(m.get('menu')))
    check('BROWSER %s: making someone admin shows them as Group admin' % tag, m.get('made') == ['Group admin'], str(m.get('made')))
    check('BROWSER %s: the photo is on the group in the list' % tag, m.get('listPhoto') is True, str(m.get('listPhoto')))
    check('BROWSER %s: no page errors' % tag, m.get('errors') == [], str(m.get('errors')))

print('%d/%d' % (sum(checks), len(checks)))
os._exit(0 if all(checks) else 1)
