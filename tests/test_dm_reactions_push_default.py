"""DM reactions persist; installed PWA notifications are default-on after the required OS prompt."""
import os, sqlite3, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update({'DATA_DIR':tempfile.mkdtemp(),'ENCRYPTION_KEY':'6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=','ORCAGENT_FRONTS_GAS':'0'})
import app_entry
d=app_entry._dashboard; app=app_entry.app
from solders.keypair import Keypair
checks=[]
def check(name,cond): checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+name)
CSRF='tok'*10; H={'X-CSRF-Token':CSRF}; BASE='https://orcagent.fun'
def member(name):
    w=str(Keypair().pubkey()); uid=d.get_or_create_user(w)
    with sqlite3.connect(d.DB_FILE) as c: c.execute('UPDATE users SET username=? WHERE id=?',(name,uid))
    return w,uid
def client(w,uid):
    c=app.test_client()
    with c.session_transaction(base_url=BASE) as s: s['wallet']=w;s['user_id']=uid;s['csrf_token']=CSRF
    return c
aw,au=member('alice'); bw,bu=member('bob'); A=client(aw,au); B=client(bw,bu)
d._send_push_notification=lambda *a,**k:None
sent=A.post(f'/api/messages/{bu}',json={'message':'hello'},headers=H,base_url=BASE).get_json()
mid=sent['message_id']
r=B.post(f'/api/messages/{mid}/reaction',json={'emoji':'❤️'},headers=H,base_url=BASE)
check('recipient can react to a DM',r.status_code==200 and r.get_json()['active'])
hist=A.get(f'/api/messages/{bu}',base_url=BASE).get_json()['messages']
check('reaction is returned with the message',hist[-1]['reactions']==[{'user_id':bu,'emoji':'❤️'}])
r=B.post(f'/api/messages/{mid}/reaction',json={'emoji':'😂'},headers=H,base_url=BASE)
check('a new emoji replaces the same user reaction',r.get_json()['reactions']==[{'user_id':bu,'emoji':'😂'}])
r=B.post(f'/api/messages/{mid}/reaction',json={'emoji':'😂'},headers=H,base_url=BASE)
check('tapping the same emoji toggles it off',r.status_code==200 and not r.get_json()['active'] and r.get_json()['reactions']==[])
cw,cu=member('carol'); C=client(cw,cu)
check('outsiders cannot react to another private thread',C.post(f'/api/messages/{mid}/reaction',json={'emoji':'👍'},headers=H,base_url=BASE).status_code==404)
check('unknown emoji is rejected',B.post(f'/api/messages/{mid}/reaction',json={'emoji':'🧨'},headers=H,base_url=BASE).status_code==400)
html=(ROOT/'templates/messages.html').read_text()
check('messages have long-press/context reaction UI','_installDmReactionGestures' in html and '_DM_REACTION_CHOICES' in html and 'contextmenu' in html)
check('iOS native text-selection/callout is disabled on message bubbles','-webkit-touch-callout:none' in html and '-webkit-user-select:none' in html and "addEventListener('selectstart'" in html)
check('emoji taps commit on pointerup with a click fallback',"addEventListener('pointerup',choose)" in html and "addEventListener('click',choose)" in html)
check('message rows preserve native vertical scrolling','#msgs-area .msg-wrap[data-mid]{touch-action:pan-y}' in html)
check('reaction UI is optimistic instead of waiting for network','_dmOptimisticReaction(previous,emoji)' in html and '_dmPaintReactions(mid,optimistic)' in html and html.index('_dmPaintReactions(mid,optimistic)') < html.index("fetch('/api/messages/'+mid+'/reaction'"))
check('reaction confirmation does not reload the whole thread','if(_activePeerId)loadThread(_activePeerId);' not in html[html.index('async function _setDmReaction'):html.index('function _installDmReactionGestures')])
check('failed reaction rolls the optimistic UI back','_dmPaintReactions(mid,previous)' in html)
check('rapid reaction taps ignore stale responses','_dmReactionSeq[mid]!==seq' in html)
check('long press opens faster than the old 520ms delay','},360);' in html)
ps=(ROOT/'static/push-subscribe.js').read_text(); js=(ROOT/'static/dashboard.js').read_text()
check('installed PWA arms default push on first trusted interaction','_armPwaDefaultPush' in ps and '_pushIsStandalone()' in ps and "Notification.permission !== 'default'" in ps)
check('Settings opt-out persists and opt-in clears it',"localStorage.setItem('oa_push_opt_out','1')" in js and "localStorage.removeItem('oa_push_opt_out')" in js)
check('background sync respects the explicit opt-out',"localStorage.getItem('oa_push_opt_out') === '1'" in ps)
raise SystemExit(0 if all(checks) else 1)
