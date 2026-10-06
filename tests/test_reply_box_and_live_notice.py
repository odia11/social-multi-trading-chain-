"""Replying on a phone: one reply box, nothing on top of it, no banner over
the answer you are reading.

Seen on an iPhone after asking @orcagent something:
- "New reply -- OrcAgent answered your platform question" slid over the very
  answer already on screen. A notification whose reply (or the open replies
  of that post, or the DM thread) is on screen is now marked read without a
  banner.
- Tapping Reply under OrcAgent's answer gave a second box ("Reply to
  Orcagent...") while the post's own "Reply to degentrader1990..." stayed:
  two boxes. The post's box now hides while a reply-to-a-reply is written,
  and comes back when it is closed, sent, or the replies are reloaded.
- While typing, the bottom bar and its POST button floated above the
  keyboard, over the reply box. It now hides while a text field has focus.
"""
import os, re, subprocess
ROOT = os.path.join(os.path.dirname(__file__), '..')
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

inapp = read('static', 'in-app-notifications.js')
show = inapp[inapp.index('function showNext(){'):inapp.index('function enqueue(')]
check('a notification about what is already on screen is marked read without a banner',
      'if(alreadyOnScreen(n)){markRead(Number(n.id)||0);refreshBadges();showNext();return}' in show
      and show.index('alreadyOnScreen(n)') < show.index('showing=true;'))
fn = inapp[inapp.index('function inView(el){'):inapp.index('function showNext(){')]
check('...on screen = the reply itself, the open replies of that post, or the DM thread with the sender',
      '.fc-reply-item[data-reply-id="' in fn and "getElementById('rbox-'+post[1])" in fn
      and "location.pathname==='/messages/'+dm[1]" in fn and 'active.wallet===peer' in fn)
# Evaluate the hash/path matching itself.
js = fn + r'''
var location={pathname:'/',origin:'https://orcagent.fun'};var window={_activePeer:null,innerHeight:800};
var document={hidden:false,documentElement:{clientHeight:800},
 querySelector:function(s){return s.indexOf('"34"')>0?{getBoundingClientRect:function(){return{width:100,height:40,top:300,bottom:340}}}:null},
 getElementById:function(){return null}};
function getComputedStyle(){return{display:'block'}}
function safeInternalLink(v){return v}
console.log(JSON.stringify([alreadyOnScreen({link:'/#post-p12-reply-34'}),alreadyOnScreen({link:'/#post-p12-reply-35'}),
  alreadyOnScreen({link:'/messages/ABC?mid=3'})]));
location.pathname='/messages/ABC';console.log(JSON.stringify([alreadyOnScreen({link:'/messages/ABC?mid=3'}),alreadyOnScreen({link:'/messages/XYZ'})]));
'''
out = subprocess.run(['node', '-e', js], capture_output=True, text=True)
lines = out.stdout.strip().splitlines()
check('...evaluated: reply 34 on screen -> no banner; reply 35 / another DM -> banner',
      lines == ['[true,false,false]', '[true,false]'])

dash = read('static', 'dashboard.js')
nest = dash[dash.index('function _feedToggleNestedReply('):dash.index('function _feedSubmitNestedReply(')]
check('one reply box at a time: the post\'s own box hides while replying to a reply, and returns on close',
      '_feedPostComposerShown(postId, false);' in nest and "if(isOpen){ _feedPostComposerShown(postId, true); return; }" in nest
      and "card.style.display = show ? '' : 'none';" in nest)
sub = dash[dash.index('function _feedSubmitNestedReply('):dash.index('function _feedSubmitNestedReply(') + 1500]
load = dash[dash.index('function _feedLoadReplies('):dash.index('function _feedLikeReply(')]
check('...and after sending, or when the replies are reloaded (no state without any box)',
      '_feedPostComposerShown(postId, true);' in sub and '_feedPostComposerShown(postId, true);' in load)

nav = read('static', 'mobile-bottom-nav.js')
check('the bottom bar (and POST) hides while a text field has focus, and returns after',
      "html.oa-kb-typing .oa-bottom-nav,html.oa-kb-typing #oa-bottom-nav{display:none!important}" in nav
      and "document.addEventListener('focusin',_syncTyping,true);" in nav
      and "document.addEventListener('focusout',function(){setTimeout(_syncTyping,60)},true);" in nav)
check('...text fields only (a button or checkbox does not hide it)',
      "/^(text|search|email|url|tel|number|password)$/i.test(el.type||'text')" in nav and "t==='TEXTAREA'" in nav)
raise SystemExit(0 if all(checks) else 1)
