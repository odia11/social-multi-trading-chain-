"""Exercise real Home rendering: poll counters without replacing loaded photos.

The app runs against a disposable database. Fake first-page responses also
cover new/deleted posts, pagination, reposts and real avatar changes.
"""
import json, os, re, sqlite3, subprocess, sys, tempfile, time, urllib.request
ROOT = os.environ.get('ORCAGENT_TEST_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

# ── in a real browser, the way Safari scrolls (no scroll anchoring) ───────
PORT = int(os.environ.get('ORCAGENT_TEST_PORT','5098'))
DATA = tempfile.mkdtemp()
ENV = dict(os.environ, DATA_DIR=DATA, ENCRYPTION_KEY='6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
           ORCAGENT_FRONTS_GAS='0', ORCAGENT_PLATFORM_POSTS='0', PYTHONPATH=ROOT)
SEED = r'''
import os, sys, sqlite3, random
sys.path.insert(0, %r)
import app_entry
d = app_entry._dashboard; app = app_entry.app
from solders.keypair import Keypair
w = str(Keypair().pubkey()); uid = d.get_or_create_user(w)
others = [str(Keypair().pubkey()) for _ in range(12)]; [d.get_or_create_user(o) for o in others]
c = sqlite3.connect(d.DB_FILE)
c.execute('INSERT INTO tos_acceptances (user_id, version, accepted_at) VALUES (?,?,datetime())', (uid, d.TOS_VERSION))
for i in range(12):
    c.execute("INSERT INTO feed_posts (wallet, content, image_url, created_at) VALUES (?,?,?, datetime('now', ?))",
              (random.choice(others), 'Post %%d about the market today, with a few words more' %% i,
               ('/static/og-orcagent.png?n=%%d' %% i) if i %% 3 == 0 else None, '-%%d seconds' %% (i * 600)))
c.execute("UPDATE users SET avatar_url='/static/og-orcagent.png'")
c.commit(); c.close()
with app.test_request_context():
    from flask import session
    session['wallet'] = w; session['csrf_token'] = 'x' * 64; session.permanent = True
    resp = app.response_class(); app.session_interface.save_session(app, session, resp)
    print('@@' + resp.headers['Set-Cookie'].split(';')[0].split('=', 1)[1])
os._exit(0)
''' % ROOT
r = subprocess.run([sys.executable, '-c', SEED], env=ENV, capture_output=True, text=True, timeout=180)
COOKIE = ([l[2:] for l in r.stdout.splitlines() if l.startswith('@@')] or [''])[-1]
server = subprocess.Popen([sys.executable, '-c',
    'import app_entry as d;d.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)' % PORT],
    env=ENV, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, os
from playwright.async_api import async_playwright
PORT, COOKIE = %d, %r
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width':int(os.environ.get('ORCAGENT_TEST_WIDTH','390')),'height':844}, is_mobile=True, has_touch=True)
        await ctx.add_init_script("localStorage.setItem('orcagent_tips_seen','1');localStorage.setItem('orca_wizard_dismissed','1')")
        await ctx.add_cookies([{'name':'orca_s','value':COOKIE,'domain':'127.0.0.1','path':'/'}])
        page = await ctx.new_page()
        errs=[]; page.on('pageerror', lambda e: errs.append(str(e)))
        await page.goto('http://127.0.0.1:%%d/' %% PORT,wait_until='load')
        await page.wait_for_selector('.fc-card .fc-avatar img')
        await page.wait_for_function("document.querySelector('.fc-card .fc-avatar img').naturalWidth>0")
        result = await page.evaluate(r"""async () => {
          var copy=x=>JSON.parse(JSON.stringify(x));
          var first=_homeFeedData[0], id='fc-card-p'+first.id;
          var original=document.getElementById(id), avatar=original.querySelector('.fc-avatar img');
          var photo=original.querySelector('.fc-post-image');
          var reply=original.querySelector('textarea'); reply.value='keep my draft';
          var nativeFetch=window.fetch;
          var response={items:copy(_homeFeedData),next_cursor:null};
          window.fetch=function(url,opts){
            if(String(url).indexOf('/api/social/feed')!==-1) return Promise.resolve({ok:true,json:async()=>copy(response)});
            return nativeFetch.apply(this,arguments);
          };
          var before=Array.from(document.querySelectorAll('.fc-card .fc-avatar img'));
          for(var n=1;n<=4;n++){
            response.items[0].view_count=n+10;
            response.items[0].like_count=n;
            response.items[0].liked_by_me=true;
            response.items[0].reply_count=n+1;
            response.items[0].repost_count=n+2;
            await loadHomeFeed();
          }
          var current=document.getElementById(id);
          var out={sameCard:current===original,sameAvatar:current.querySelector('.fc-avatar img')===avatar,
            allAvatarsRetained:before.every(img=>img.isConnected),
            draft:current.querySelector('textarea').value,
            like:current.querySelector('.fc-like-count').textContent,
            views:current.querySelector('.fc-view-count').textContent,
            liked:current.querySelector('.fc-like-btn').classList.contains('liked'),
            samePostPhoto:!photo || current.querySelector('.fc-post-image')===photo};
          // Real content edits keep the decoded avatar and the reply draft.
          response.items[0].content='Edited post text'; await loadHomeFeed();
          current=document.getElementById(id);
          out.editAvatar=current.querySelector('.fc-avatar img')===avatar;
          out.editDraft=current.querySelector('textarea').value;
          out.editText=current.textContent.includes('Edited post text');
          // A genuine profile-photo change must still take effect.
          response.items[0].avatar_url='/static/og-orcagent.png?changed-avatar=1'; await loadHomeFeed();
          out.changedAvatar=document.getElementById(id).querySelector('.fc-avatar img')!==avatar
            && document.getElementById(id).querySelector('.fc-avatar img').getAttribute('src').includes('changed-avatar=1');
          // A shorter first page does not mean we have paginated; remove its
          // deleted post rather than accidentally retaining it as older data.
          var removed=response.items.pop(); await loadHomeFeed();
          out.shortPageDelete=!document.getElementById('fc-card-p'+removed.id);
          response.items.push(removed); await loadHomeFeed();
          // Simulate an older page, then a new post pushing the page boundary.
          var pageOne=copy(response.items), extra=copy(pageOne).map((e,i)=>Object.assign(e,{id:10000+i,created_at:'2020-01-01 00:00:00',timestamp:'2020-01-01 00:00:00'}));
          _homeFeedData=_homeFeedData.concat(extra); _homeFeedNextCursor='older-cursor';
          await renderHomeFeed(extra);
          var tail=document.getElementById('fc-card-p10000'), tailAvatar=tail.querySelector('.fc-avatar img');
          var boundaryId='fc-card-p'+pageOne[pageOne.length-1].id;
          response.items=[Object.assign(copy(pageOne[0]),{id:99999,created_at:'2099-01-01 00:00:00',timestamp:'2099-01-01 00:00:00'})].concat(pageOne.slice(0,-1));
          response.next_cursor='first-page-cursor'; await loadHomeFeed();
          out.olderPage=tail.isConnected && tail.querySelector('.fc-avatar img')===tailAvatar;
          out.boundaryRetained=!!document.getElementById(boundaryId);
          out.newPost=!!document.getElementById('fc-card-p99999');
          out.cursor=_homeFeedNextCursor;
          out.dataCount=_homeFeedData.length;
          var deleted=response.items[2]; response.items.splice(2,1); await loadHomeFeed();
          out.deleted=!document.getElementById('fc-card-p'+deleted.id);
          // Repost wrappers retain the original author's loaded avatar too.
          var src=copy(response.items[0]);
          var rep=Object.assign(copy(src),{id:88888,type:'repost',repost_of:'p'+src.id,
            original:Object.assign(copy(src),{kind:'p'})});
          _homeFeedData=[rep]; renderHomeFeed();
          var wrapper=document.querySelector('.fc-repost-wrap'), repAvatar=wrapper.querySelector('.fc-avatar img');
          _homeFeedData=[Object.assign(copy(rep),{view_count:42})]; renderHomeFeed();
          out.repost=wrapper.isConnected && document.querySelector('.fc-repost-wrap')===wrapper
            && wrapper.querySelector('.fc-avatar img')===repAvatar;
          _homeFeedData=[]; renderHomeFeed(); out.empty=!document.querySelector('.fc-card');
          window.fetch=nativeFetch; return out;
        }""")
        result['errors']=errs
        await b.close()
        print('@@'+json.dumps(result))
asyncio.run(main())
''' % (PORT, COOKIE)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen('http://127.0.0.1:%d/static/og-orcagent.png' % PORT,timeout=2);break
        except Exception: time.sleep(1)
    r=subprocess.run([sys.executable,'-c',DRIVER],capture_output=True,text=True,timeout=90)
    lines=[x[2:] for x in r.stdout.splitlines() if x.startswith('@@')]
    result=json.loads(lines[-1]) if lines else {}
    if not result: print(r.stdout[-1000:],r.stderr[-3000:])
finally:
    server.terminate()
print('measured:',json.dumps(result))
for key in ['sameCard','sameAvatar','allAvatarsRetained','samePostPhoto','liked','editAvatar','editText',
            'changedAvatar','shortPageDelete','olderPage','boundaryRetained','newPost','deleted','repost','empty']:
    check(key,result.get(key) is True)
check('reply draft survives counters and content edits',result.get('draft')=='keep my draft' and result.get('editDraft')=='keep my draft')
check('live counts update in place',result.get('like')=='4' and result.get('views')=='14 views')
check('older-page cursor and all loaded posts survive refresh',result.get('cursor')=='older-cursor' and result.get('dataCount')==25)
check('no browser errors',bool(result) and not result.get('errors'))
print('%d/%d' % (sum(checks),len(checks)))
sys.exit(0 if all(checks) else 1)
