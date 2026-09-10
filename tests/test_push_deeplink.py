"""Tapping a surge alert has to land on that token. Four links in the chain,
and a break in any one of them looks identical from the outside: the app
opens, on the wrong page, with no error anywhere.

  1. the server puts a url in the push payload
  2. the service worker carries it onto the notification
  3. the click handler navigates there
  4. Live Market reads ?mint= and shows that token

Link 3 is where it was broken, and in a way no error would ever reveal.

The service worker is executed in node against a fake `clients` registry, so
these drive the real handler rather than reading it."""
import json, os, re, subprocess, sys, tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
SW   = open(REPO + '/static/sw.js').read()
LM   = open(REPO + '/static/live-market-pro.js').read()
PY_  = open(REPO + '/dashboard.py').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

# ── 1. the server ──
ns = re.search(r'def notify_surge\(surge: dict\):.*?\n(?=def )', PY_, re.S).group(0)
# Matched on the url ARGUMENT rather than the whole call text. Pinning the
# full argument list made this fail the day an icon was added alongside it --
# a change that has nothing to do with deep-linking, which is what this
# check is about.
check('the push carries a url built from the surge mint',
      "urllib.parse.quote(mint, safe='')" in ns
      and re.search(r'_send_push_notifications_bulk\([^)]*\bpush_url\b', ns))
snd = re.search(r'def _send_push_notification_sync\(.*?\n(?=def )', PY_, re.S).group(0)
check('...and that url reaches the payload the browser receives',
      "'url': url" in snd)

# ── 2 + 3. the service worker, actually executed ──
harness = SW + r'''
// --- a fake window registry ---
var _opened = null, _focused = null, _navigated = null;
function mkClient(url, canNavigate){
  var c = { url: url, focus: function(){ _focused = this.url; return Promise.resolve(this); } };
  if (canNavigate) c.navigate = function(u){ _navigated = u; this.url = u; return Promise.resolve(this); };
  return c;
}
var _clients = [];
var clients = {
  matchAll: function(){ return Promise.resolve(_clients); },
  openWindow: function(u){ _opened = u; return Promise.resolve(null); }
};
var self_listeners = {};
var self = {
  location: { origin: 'https://orcagent.fun' },
  addEventListener: function(n, f){ self_listeners[n] = f; },
  registration: { showNotification: function(t, o){ self.__shown = {title:t, opts:o}; return Promise.resolve(); } },
  clients: clients
};
globalThis.self = self; globalThis.clients = clients;
eval(REDEFINE);

function reset(list){ _clients = list; _opened = _focused = _navigated = null; }
function click(url){
  var waited = null;
  self_listeners['notificationclick']({
    notification: { close: function(){}, data: { url: url } },
    waitUntil: function(p){ waited = p; }
  });
  return waited.then(function(){ return {opened:_opened, focused:_focused, navigated:_navigated}; });
}

// what the push handler produces, so the data.url path is exercised too
self_listeners['push']({
  data: { json: function(){ return {title:'$PEIPEI +98.9% (5m)', body:'x', url:'/live-market?mint=0xABC'}; } },
  waitUntil: function(p){ return p; }
});

var out = {};
out.push_data_url = self.__shown.opts.data.url;

var TARGET = 'https://orcagent.fun/live-market?mint=0xABC';
Promise.resolve()
 .then(function(){ reset([]); return click('/live-market?mint=0xABC'); })
 .then(function(r){ out.no_window = r; })
 .then(function(){ reset([mkClient('https://orcagent.fun/live-market', true)]); return click('/live-market?mint=0xABC'); })
 .then(function(r){ out.open_on_live_market = r; })
 .then(function(){ reset([mkClient('https://orcagent.fun/home', true)]); return click('/live-market?mint=0xABC'); })
 .then(function(r){ out.open_elsewhere = r; })
 .then(function(){ reset([mkClient(TARGET, true)]); return click('/live-market?mint=0xABC'); })
 .then(function(r){ out.already_there = r; })
 .then(function(){ reset([mkClient('https://orcagent.fun/home', false)]); return click('/live-market?mint=0xABC'); })
 .then(function(r){ out.no_navigate_support = r; })
 .then(function(){ reset([mkClient('https://evil.example/whatever', true)]); return click('/live-market?mint=0xABC'); })
 .then(function(r){ out.foreign_window = r; })
 .then(function(){ reset([mkClient('https://orcagent.fun/home', true)]); return click(undefined); })
 .then(function(r){ out.no_url = r; })
 .then(function(){ console.log(JSON.stringify(out)); });
'''
# the SW registers on the real `self`; re-run the registrations against the fake one
harness = harness.replace("self.addEventListener('install'", "REGISTER_START; self.addEventListener('install'", 1)
harness = 'var REDEFINE = "";\n' + harness.replace('REGISTER_START; ', '')
# simplest: strip the top-level `self.` binding problem by declaring self first
harness = harness.replace('var REDEFINE = "";\n', '')
src = '''
var _shown=null,_opened=null,_focused=null,_navigated=null,_clients=[];
var clients={matchAll:function(){return Promise.resolve(_clients);},
             openWindow:function(u){_opened=u;return Promise.resolve(null);}};
var listeners={};
var self={location:{origin:'https://orcagent.fun'},
          addEventListener:function(n,f){listeners[n]=f;},
          registration:{showNotification:function(t,o){_shown={title:t,opts:o};return Promise.resolve();}},
          clients:clients};
''' + SW + '''
function mkClient(url, canNavigate){
  var c={url:url, focus:function(){_focused=this.url;return Promise.resolve(this);}};
  if(canNavigate) c.navigate=function(u){_navigated=u;this.url=u;return Promise.resolve(this);};
  return c;
}
function reset(list){_clients=list;_opened=_focused=_navigated=null;}
function click(url){
  var waited=null;
  listeners['notificationclick']({notification:{close:function(){},data:url?{url:url}:null},
                                  waitUntil:function(p){waited=p;}});
  return waited.then(function(){return {opened:_opened,focused:_focused,navigated:_navigated};});
}
listeners['push']({data:{json:function(){return {title:'t',body:'b',url:'/live-market?mint=0xABC'};}},
                   waitUntil:function(p){return p;}});
var out={push_data_url:_shown.opts.data.url};
var TARGET='https://orcagent.fun/live-market?mint=0xABC';
Promise.resolve()
 .then(function(){reset([]);return click('/live-market?mint=0xABC');}).then(function(r){out.no_window=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/live-market',true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.open_on_live_market=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/home',true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.open_elsewhere=r;})
 .then(function(){reset([mkClient(TARGET,true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.already_there=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/home',false)]);return click('/live-market?mint=0xABC');}).then(function(r){out.no_navigate=r;})
 .then(function(){reset([mkClient('https://evil.example/x',true)]);return click('/live-market?mint=0xABC');}).then(function(r){out.foreign=r;})
 .then(function(){reset([mkClient('https://orcagent.fun/home',true)]);return click(null);}).then(function(r){out.no_url=r;})
 .then(function(){console.log(JSON.stringify(out));});
'''
# Into a temp directory, not the repo. This used to write _sw.js next to
# dashboard.py, which left the working tree dirty after every single test
# run -- and the file had been committed once by accident, so it also sat in
# git as a stale half-copy of sw.js glued to this harness, looking for all
# the world like source.
with tempfile.TemporaryDirectory() as _tmp:
    _harness_path = os.path.join(_tmp, 'sw_harness.js')
    with open(_harness_path, 'w', encoding='utf-8') as _f:
        _f.write(src)
    res = subprocess.run(['node', _harness_path], capture_output=True, text=True)
assert res.returncode == 0, res.stderr
R = json.loads(res.stdout)
print(json.dumps(R, indent=2) + '\n')

T = 'https://orcagent.fun/live-market?mint=0xABC'
check('the notification carries the url from the push payload',
      R['push_data_url'] == '/live-market?mint=0xABC')
check('with nothing open, tapping opens the token', R['no_window']['opened'] == T)
check('with a tab ALREADY on Live Market, it navigates that tab to the token — '
      'the old handler just focused it, so you landed on the page you left',
      R['open_on_live_market']['navigated'] == T and R['open_on_live_market']['opened'] is None)
check('with a tab on another page, it navigates that one too rather than opening '
      'a second window', R['open_elsewhere']['navigated'] == T)
check('a tab already showing that exact token is only focused, not reloaded',
      R['already_there']['focused'] == T and R['already_there']['navigated'] is None)
check('a browser without navigate() opens the target rather than focusing the '
      'wrong page — the right token in a new window beats the wrong one in an old',
      R['no_navigate']['opened'] == T and R['no_navigate']['focused'] is None)
check('a window belonging to another site is never touched',
      R['foreign']['navigated'] is None and R['foreign']['focused'] is None
      and R['foreign']['opened'] == T)
check('a notification with no url at all still opens the app rather than throwing',
      R['no_url']['navigated'] == 'https://orcagent.fun/' or R['no_url']['opened'] == 'https://orcagent.fun/')
# The comment in sw.js quotes the old line to explain it, so check the CODE.
_sw_code = '\n'.join(l for l in SW.split('\n') if not l.strip().startswith('//'))
check('the old substring match is gone from the code — "/" was a substring of '
      'every url, so any open tab matched and was merely focused',
      'client.url.indexOf(url)' not in _sw_code)
check('the origin check that replaced it compares from position 0, not anywhere '
      'in the string', "client.url.indexOf(self.location.origin) !== 0" in _sw_code)

# ── 4. Live Market ──
check('Live Market reads ?mint= from the url', "URLSearchParams(location.search).get('mint')" in LM)
check('the deep-linked token is queued and injected when the first feed load '
      'actually finishes, instead of after a guessed 900ms delay',
      '_pendingDeepLinkMint = _qMint' in LM and 'setTimeout(function(){ prependSearchedToken' not in LM)
check('...and injected from .finally, so a failed scanner load still shows it',
      re.search(r'\.finally\(function\(\)\s*\{[^}]*_pendingDeepLinkMint', LM, re.S))
check('it is consumed once, not re-injected on every 15s poll',
      '_pendingDeepLinkMint = null;' in LM)
check('the pinned token survives the polls — mergeTokenUpdates only updates in '
      'place and never drops a row', 'ST.tokens.forEach' in LM and 'byMint[t.mint]' in LM)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
