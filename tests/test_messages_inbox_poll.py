"""Real mobile inbox polls retain rows/photos while updating DM and group metadata."""
import json, os, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT = os.environ.get('ORCAGENT_TEST_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

PORT = 5103
DATA = tempfile.mkdtemp()
ENV = dict(os.environ, DATA_DIR=DATA, ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', PYTHONPATH=ROOT)
SEED = r'''
import os, sys, sqlite3
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
w = str(Keypair().pubkey()); me = d.get_or_create_user(w)
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (me, d.TOS_VERSION))
c.commit()
c.close()
peers = [d.get_or_create_user(str(Keypair().pubkey())) for _ in range(3)]
c = sqlite3.connect(d.DB_FILE)
for n, pid in enumerate(peers):
    c.execute('UPDATE users SET username=?, avatar_url=? WHERE id=?', ('trader%%d' %% n, '/static/og-orcagent.png', pid))
    for i in range(60):
        s, r = (me, pid) if i %% 3 else (pid, me)
        c.execute("INSERT INTO direct_messages (sender_id, receiver_id, message, created_at, is_read) VALUES (?,?,?, datetime('now', ?), 1)",
                  (s, r, 'Message %%d with trader%%d about the market, entries and exits today' %% (i, n), '-%%d minutes' %% ((60 - i) * 7)))
c.commit(); c.close()
with app.test_request_context():
    from flask import session
    session['wallet'] = w; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    print('@@' + json.dumps({'cookie': resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1], 'peers': peers}), flush=True)
os._exit(0)
'''.replace('json.dumps', '__import__("json").dumps') % ROOT
r = subprocess.run([sys.executable, '-c', SEED], env=ENV, capture_output=True, text=True, timeout=180)
SEEDED = json.loads(([l[2:] for l in r.stdout.splitlines() if l.startswith('@@')] or ['{}'])[-1] or '{}')
if not SEEDED: print(r.stdout[-1500:], r.stderr[-1500:])
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d._dashboard._rate_ok=lambda *a,**k:True;'
    'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

try:
    for _ in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/static/og-orcagent.png' % PORT, timeout=2); break
        except Exception: time.sleep(1)
    import asyncio
    from playwright.async_api import async_playwright
    async def browser():
        async with async_playwright() as pw:
            b = await pw.chromium.launch(args=['--no-sandbox'])
            ctx = await b.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True)
            await ctx.add_cookies([{'name':'orca_s','value':SEEDED['cookie'],'domain':'127.0.0.1','path':'/'}])
            page = await ctx.new_page(); errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            groups={'ok':True,'chats':[{'id':7,'name':'Beta testers','photo':'/static/og-orcagent.png','unread':0,'last':{'text':'gm','kind':'text','mine':True,'created_at':'2026-10-08 18:00:00'}}]}
            await page.route('**/api/group-chats',lambda r:r.fulfill(json=groups))
            await page.goto('http://127.0.0.1:%d/messages'%PORT,wait_until='load')
            await page.wait_for_selector('#conv-list .conv-avatar img',state='attached')
            await page.wait_for_selector('#gc-section img',state='attached')
            await page.wait_for_function('_lastConvSig !== null && !window._convLoadInFlight')
            out=await page.evaluate('''async () => {
              const out={}; const list=document.getElementById('conv-list');
              const snapshot=JSON.parse(JSON.stringify(_conversations));
              const first=snapshot[0], second=snapshot[1];
              const row=list.querySelector('[data-peer-id="'+first.peer_id+'"]'), img=row.querySelector('img');
              const other=list.querySelector('[data-peer-id="'+second.peer_id+'"]');
              const g=document.querySelector('[data-gc="7"]'), gi=g.querySelector('img');
              const nativeFetch=window.fetch; let response=snapshot;
              window.fetch=(url,opts)=>url==='/api/messages'?Promise.resolve({json:()=>Promise.resolve({ok:true,conversations:response})}):nativeFetch(url,opts);
              first.unread=3;first.last_msg='New live preview';first.peer_online=true;
              await loadConversations();
              out.dmRetained=row===list.querySelector('[data-peer-id="'+first.peer_id+'"]')&&img===row.querySelector('img')&&other===list.querySelector('[data-peer-id="'+second.peer_id+'"]');
              out.dmUpdated=row.querySelector('.conv-preview').textContent.includes('New live preview')&&row.querySelector('.conv-badge').textContent==='3'&&!!row.querySelector('.msgs-online-dot');
              for(let i=0;i<15;i++){first.unread=i+1;await loadConversations();}
              out.repeatedPolls=img===row.querySelector('img')&&row===list.querySelector('[data-peer-id="'+first.peer_id+'"]');
              first.peer_username='Renamed trader';first.peer_verified=true;first.peer_avatar='/static/og-orcagent.png?updated';
              await loadConversations();
              out.profileUpdated=img===row.querySelector('img')&&img.getAttribute('src').endsWith('?updated')&&row.querySelector('.conv-name').textContent==='Renamed trader'&&!!row.querySelector('.conv-verified');
              response=[second,first,...snapshot.slice(2)];await loadConversations();
              out.reordered=list.children[0]===other&&list.children[1]===row;
              let opens=0;const open=_openThread;_openThread=()=>opens++;
              row.querySelector('.conv-row').dispatchEvent(new MouseEvent('click',{bubbles:true}));
              out.oneHandler=opens===1;_openThread=open;
              second.peer_online=true;await loadConversations();
              const active=document.querySelector('.oa-active-peer[data-peer-id="'+first.peer_id+'"]');
              const activeImg=active.querySelector('img');
              response=[first,second,...snapshot.slice(2)];await loadConversations();
              out.activeRetained=active===document.querySelector('.oa-active-peer[data-peer-id="'+first.peer_id+'"]')&&activeImg===active.querySelector('img');
              let mutations=0;const mo=new MutationObserver(ms=>mutations+=ms.length);mo.observe(document.getElementById('gc-section'),{subtree:true,childList:true,attributes:true,characterData:true});
              for(let i=0;i<5;i++)await OrcAgentGroupChats.reload();
              await new Promise(r=>setTimeout(r,0));mo.disconnect();
              out.groupUnchanged=mutations===0&&g===document.querySelector('[data-gc="7"]')&&gi===g.querySelector('img');
              window.__savedGroup=g;window.__savedGroupImg=gi;
              _setConvFilter('unread');out.unreadFilter=list.querySelectorAll('.conv-row-wrap').length===1;
              _setConvFilter('all');out.allFilter=list.querySelectorAll('.conv-row-wrap').length===snapshot.length;
              const search=document.getElementById('msgs-search');search.value='Renamed';_filterConvs('Renamed');
              out.search=row.style.display===''&&list.querySelector('[data-peer-id="'+second.peer_id+'"]').style.display==='none';
              search.value='';_filterConvs('');
              response=[second];await loadConversations();out.deleted=!row.isConnected;
              response=[];await loadConversations();out.empty=!!list.querySelector('.oa-inbox-empty');
              response=snapshot;await loadConversations();out.repopulated=list.querySelectorAll('.conv-row-wrap').length===snapshot.length;
              const resolvers=[];let calls=0;
              window.fetch=(url,opts)=>url==='/api/messages'?(calls++,new Promise(resolve=>resolvers.push(resolve))):nativeFetch(url,opts);
              const pending=loadConversations(),overlap=loadConversations();
              out.singleFlight=calls===1;resolvers.forEach(resolve=>resolve({json:()=>Promise.resolve({ok:true,conversations:snapshot})}));await Promise.all([pending,overlap]);
              const stable=list.querySelector('img');
              window.fetch=()=>Promise.reject(new Error('Temporary test outage'));await loadConversations();
              out.networkFailureRetains=stable===list.querySelector('img');
              window.fetch=nativeFetch;
              const visible=el=>getComputedStyle(el).display!=='none';
              out.directSeparated=visible(list)&&!visible(document.getElementById('gc-section'));
              const searchState=document.getElementById('msgs-search');searchState.value='Renamed';_filterConvs('Renamed');
              _setInboxTab('groups');
              out.groupsSeparated=!visible(list)&&visible(document.getElementById('gc-section'))&&searchState.value==='';
              searchState.value='Beta';_filterConvs('Beta');document.dispatchEvent(new Event('oa-inbox-tabchange'));
              _setConvFilter('unread');
              out.groupUnreadEmpty=!document.querySelector('[data-gc="7"]')&&document.getElementById('gc-section').textContent.includes('No unread');
              _setInboxTab('direct');
              out.directStateRetained=searchState.value==='Renamed'&&_convFilter==='all';
              _setInboxTab('groups');out.groupFilterRetained=_convFilter==='unread';
              _setConvFilter('all');_setInboxTab('direct');
              window.__savedGroup=document.querySelector('[data-gc="7"]');window.__savedGroupImg=__savedGroup.querySelector('img');
              return out;
            }''')
            groups['chats'][0]['last']['text']='Updated group preview';groups['chats'][0]['unread']=4
            out['groupUpdated']=await page.evaluate('''async()=>{await OrcAgentGroupChats.reload();return __savedGroup===document.querySelector('[data-gc="7"]')&&__savedGroupImg===__savedGroup.querySelector('img')&&__savedGroup.querySelector('.conv-preview').textContent.includes('Updated group preview')&&__savedGroup.querySelector('.conv-badge').textContent==='4';}''')
            groups['chats'][0]['photo']='/static/og-orcagent.png?newgroup'
            out['groupPhotoUpdated']=await page.evaluate('''async()=>{await OrcAgentGroupChats.reload();return __savedGroupImg===__savedGroup.querySelector('img')&&__savedGroupImg.getAttribute('src').endsWith('?newgroup');}''')
            groups['chats']=[]
            out['groupEmpty']=await page.evaluate('''async()=>{await OrcAgentGroupChats.reload();return !document.querySelector('[data-gc="7"]')&&!!document.querySelector('.gc-cta');}''')
            out['noBrowserErrors']=not errors
            if errors: print('browser errors:',errors)
            for name,value in out.items():check('BROWSER: '+name,value)
            await b.close()
    asyncio.run(browser())
finally:
    server.terminate()
sys.exit(0 if checks and all(checks) else 1)
