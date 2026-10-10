"""Notifications: tabs spread over the width, each alert under the right tab;
Messages: the "Active now" ring is a whole circle.

- Trades / Social / Tips sat bunched on the left; they now share the width.
- A "$TOKEN is trending" alert landed under Social, drawn with a like's
  heart. It is a market alert: it is under Trades with a flame icon now, and
  system notices (e.g. "you've been verified") get the bell, not the heart.
- The green ring around an "Active now" avatar is drawn 4px outside it, but
  its scrolling row had only 2px of room above it, so the top was cut off.
"""
import os, re, subprocess
ROOT = os.path.join(os.path.dirname(__file__), '..')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

html = read('templates', 'notifications.html')
check('the three tabs share the full width',
      '.ntf-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))' in html
      and 'text-align:center' in html[html.index('.ntf-tab{'):html.index('.ntf-tab{') + 400])

# Run the real split and icon choice from the page against sample notifications.
start = html.index('function _rowHtml(n){')
row_fn = html[start:html.index('\nfunction _shareTrade(', start)]
render = html[html.index('function _render(){'):html.index('// ── SWIPE-TO-DELETE')]
split = render[render.index('  var NOTIF_TRADE_TYPES'):render.index('  rows.sort(')]
js = ('var _activeTab, _personal, _selectMode=false;\n'
      'function _esc(s){return String(s)}\nfunction _ntfContentHtml(n){return n.content}\n'
      'function _parseTradeContent(c){return {positive:true,headline:c,chip:""}}\n'
      'function _buildPersonalRow(n,u,icon){return icon}\n' + row_fn + '\n'
      'function tab(t){ _activeTab=t; var rows=[];\n' + split + '\n return rows.map(function(r){return r.n.type+":"+_rowHtml(r.n)}).join(",") }\n'
      '_personal=[{type:"trending",content:"x"},{type:"like",content:"x"},{type:"trade",content:"x"},'
      '{type:"system",content:"x"},{type:"tip",content:"x"},{type:"bridge",content:"x"},{type:"deposit",content:"You received 1 SOL"}];\n'
      'console.log(JSON.stringify({trades:tab("trades"),social:tab("social"),tips:tab("tips")}))')
out = subprocess.run(['node', '-e', js], capture_output=True, text=True)
import json
got = json.loads(out.stdout or '{}') if out.returncode == 0 else {}
print(out.stderr[:300]) if out.returncode else None
check('a trending alert is under Trades, with a flame -- not under Social with a heart',
      'trending:market' in got.get('trades', '') and 'trending' not in got.get('social', ''))
check('...trades and bridges stay under Trades, likes under Social, tips under Tips',
      'trade:' in got.get('trades', '') and 'bridge:' in got.get('trades', '')
      and 'like:social' in got.get('social', '') and got.get('tips') == 'tip:tip')
check('confirmed deposits appear under Trades with the funds icon',
      'deposit:tip' in got.get('trades', '') and 'deposit' not in got.get('social', ''))
check('...and a system notice gets the bell, not the heart', 'system:system' in got.get('social', ''))
check('the flame icon exists', "'market':" in html and '.ntf-icon.market{' in html)

css = read('static', 'messages-inbox.css')
row = re.search(r'#msgs-left \.oa-active-row\{([^}]*)\}', css).group(1)
pad_top = int(re.search(r'padding:(\d+)px', row).group(1))
av = re.search(r'#msgs-left \.oa-active-av\{([^}]*)\}', css).group(1)
ring = max(int(x) for x in re.findall(r'0 0 0 (\d+)px', av))
check(f'the "Active now" ring ({ring}px outside the avatar) fits inside its scrolling row ({pad_top}px)',
      pad_top >= ring)
check('phones fetch the new stylesheet (stamped with the deploy version)',
      'href="/static/messages-inbox.css' in read('messages_premium_ui.py')
      and "'messages-inbox.css'" in read('static', 'app-ux.js'))
raise SystemExit(0 if all(checks) else 1)
