"""Holding a DM opens the reaction menu and it stays open (Instagram style).

Seen on an iPhone: a long press on a message showed iOS "Copy / Look Up /
Translate" instead of reactions. The menu did open while the finger was down,
but letting go fires a click on the bubble, and that click closed the menu the
same moment -- so all anyone saw was the native text menu (or nothing).

- The click that ends the long press is swallowed; the menu stays open.
- "+" opens more reactions (all accepted by the server, still a closed set).
  It opens on click only: the grid grows and moves the menu, so a click that
  followed a pointerup would land outside it, or on an emoji.
- Text selection is off on bubbles, so "Copy text" lives in the menu.
- The menu is measured unscaled (its opening animation starts at 92%), so it
  never runs off a 360px screen, and it sits above the message.
- Desktop: Copy Trades is a pill sized to its label; the 42px square made the
  label run out of the button and over the "..." button.
"""
import os, re, sqlite3, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

html = (ROOT / 'templates/messages.html').read_text(encoding='utf-8')
gest = html[html.index('function _installDmReactionGestures(){'):html.index('/* Tip messages')]
check('the click that ends a long press no longer closes the menu it just opened',
      '_dmSwallowClickUntil=Date.now()+1500;' in gest
      and re.search(r"if\(_dmSwallowClickUntil&&Date\.now\(\)<_dmSwallowClickUntil&&!\(_dmReactionMenu&&_dmReactionMenu\.contains\(e\.target\)\)\)\{\s*_dmSwallowClickUntil=0; e\.preventDefault\(\); e\.stopPropagation\(\); return;", gest)
      and '},true);' in gest)
check('...and a new press resets it, so a later tap is never eaten', '_dmSwallowClickUntil=0;\n    if(e.pointerType' in gest)
menu = html[html.index('function _openDmReactionMenu(wrap,x,y){'):html.index('var _dmReactionSeq=Object.create(null);')]
check('"+" opens more reactions, on click only',
      "more.addEventListener('click',openMore);" in menu and "addEventListener('pointerup',openMore)" not in menu
      and '_DM_REACTION_MORE.forEach' in menu)
check('"Copy text" in the menu (text selection is off on bubbles)',
      'navigator.clipboard.writeText(text)' in menu and "'Copy text'" in menu)
place = html[html.index('function _dmPlaceMenu('):html.index('function _openDmReactionMenu(')]
check('the menu is measured unscaled and placed above the message',
      'w=menu.offsetWidth, h=menu.offsetHeight' in place and 'menu.getBoundingClientRect()' not in place
      and "wrap.querySelector('.msg-bubble')" in place)

m = re.search(r"var _DM_REACTION_CHOICES=(\[[^\]]*\]);", html); n = re.search(r"var _DM_REACTION_MORE=(\[[^\]]*\]);", html)
offered = set(eval(m.group(1))) | set(eval(n.group(1)))
check('every reaction the menu offers is accepted by the server -- and only those',
      offered == set(d._DM_REACTION_EMOJIS) and len(offered) > 20)

CSRF = 'tok' * 10; H = {'X-CSRF-Token': CSRF}; BASE = 'https://orcagent.fun'
def member(name):
    w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
    with sqlite3.connect(d.DB_FILE) as c: c.execute('UPDATE users SET username=? WHERE id=?', (name, uid))
    c = app.test_client()
    with c.session_transaction(base_url=BASE) as s: s['wallet'] = w; s['user_id'] = uid; s['csrf_token'] = CSRF
    return c, uid
d._send_push_notification = lambda *a, **k: None
A, au = member('alice'); B, bu = member('bob')
mid = A.post(f'/api/messages/{bu}', json={'message': 'gm'}, headers=H, base_url=BASE).get_json()['message_id']
r = B.post(f'/api/messages/{mid}/reaction', json={'emoji': '🚀'}, headers=H, base_url=BASE)
check('a "+" reaction is saved', r.status_code == 200 and r.get_json()['reactions'] == [{'user_id': bu, 'emoji': '🚀'}])
check('free text is still refused',
      B.post(f'/api/messages/{mid}/reaction', json={'emoji': '<b>x</b>'}, headers=H, base_url=BASE).status_code == 400)

css = (ROOT / 'static/messages-ui.css').read_text(encoding='utf-8')
desk = css[css.index('@media(min-width:768px){\n  html body .msgs-thread-hdr .msgs-copy-trades-btn'):]
desk = desk[:desk.index('\n}\n')]
check('desktop: Copy Trades is a pill sized to its label, not a 42px square',
      'width:auto!important' in desk and 'padding:0 16px!important' in desk and 'white-space:nowrap!important' in desk
      and '.msgs-copy-trades-label{display:inline!important' in desk)
raise SystemExit(0 if all(checks) else 1)
