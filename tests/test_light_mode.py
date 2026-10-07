"""Light mode (white with gold), on the whole app, with a switch.

The light theme is derived from the dark stylesheets (theme_light.py) plus a
runtime for colours JavaScript writes (static/theme-light.js). What must hold:
- the brand: dark surfaces become warm white (cards white), light text dark
  ink, gold stays gold (a little deeper on a white page), coloured text is
  darkened until it reads on white, text on a gold button keeps its colour,
  white knobs stay white, the OrcAgent mark keeps its dark triangle;
- dark mode is untouched: every derived rule is scoped to
  html[data-theme="light"];
- the cascade holds: every colour property of a rule is restated, so a rule
  whose colour does not change is not beaten by a companion it used to beat;
- the server paints a light page light from its first byte (cookie), so
  there is no dark flash;
- the switch is in the navbar menu, the phone menu and Settings, and is
  remembered per device;
- the Python mapping and its JavaScript port agree.
"""
import json, os, re, subprocess, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import theme_light as t  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

# ── the palette ──
m = t.map_token
check('the dark page becomes a warm white, cards become white',
      m('#0a0b0e', 'bg') == '#f8f6f3' and m('#101216', 'bg') == '#fefefe')
check('light text becomes dark ink; muted text a mid grey',
      m('#eef1f5', 'text') == '#0c0d0f' and m('#8a919c', 'text') == '#636975')
check('gold text deepens to antique gold so it reads on white (contrast >= 3)',
      m('#f7b955', 'text') == '#c0872b' and t._contrast_on_white(*t.parse_color('#c0872b')[:3]) >= 3.0)
check('gold buttons stay gold, a little deeper on a white page', m('#f7b955', 'bg') == '#de9a2c')
check('a translucent gold tint stays as it is', m('rgba(247,185,85,.12)', 'bg') == 'rgba(247,185,85,0.12)')
check('green and red text stay green and red', m('#3ad29b', 'text') == '#26a879' and m('#ff5c5c', 'text') == '#ff5c5c')
check('white knobs stay white; white overlays turn into soft dark ones',
      m('#fff', 'bg') == '#ffffff' and m('rgba(255,255,255,.06)', 'bg') == 'rgba(19,20,22,0.06)')
check('a black scrim still dims the page; shadows soften',
      m('rgba(0,0,0,.6)', 'bg') == 'rgba(0,0,0,0.3)' and m('rgba(0,0,0,.4)', 'shadow') == 'rgba(0,0,0,0.14)')

# ── stylesheets ──
css = (':root{--accent:#f7b955;--bg:#0a0b0e}'
       '.btn{background:var(--accent);color:#0a0b0e}'
       '.chip{background:#121820;color:#8a919c;border-radius:9px}.chip.on{background:var(--x);color:#0b0d10}'
       '.gold{background:#f7b955;color:#111}'
       '.pt-nb-logo-mark::before{border-bottom:11px solid #0a0b0e}'
       '@media (max-width:600px){.m{border:1px solid #21252c!important}}'
       '@keyframes k{from{color:#fff}}')
out = t.light_css(css)
check('every derived rule is scoped to light mode, so dark mode is untouched',
      all(line.startswith(('html[data-theme="light"]', '@media')) for line in out.split('\n')))
check('variables are mapped on the root', 'html[data-theme="light"]{--accent:#de9a2c;--bg:#f8f6f3}' in out)
check('text on a gold button keeps its colour (also when the gold comes from a variable)',
      'html[data-theme="light"] .btn{background:var(--accent);color:#0a0b0e}' in out
      and 'html[data-theme="light"] .gold{background:#de9a2c;color:#111}' in out)
check('a colour property without a literal colour is restated too, so the cascade holds',
      'html[data-theme="light"] .chip.on{background:var(--x);color:#f7f6f2}' in out)
check('...and only colour properties are (no radius, no widths)', 'border-radius' not in out)
check('the OrcAgent mark keeps its dark triangle', 'logo-mark' not in out)
check('media queries and !important carry over; keyframes are left alone',
      '@media (max-width:600px){html[data-theme="light"] .m{border:1px solid #e6e4de!important}}' in out
      and 'keyframes' not in out)

# ── the Python mapping and its JavaScript port agree ──
VECTORS = [(c, r) for c in ('#0a0b0e', '#101216', '#16191f', '#21252c', '#eef1f5', '#8a919c', '#565d68', '#f7b955',
                            '#3ad29b', '#ff5c5c', '#4da3ff', '#fff', '#000', 'rgba(255,255,255,.06)', 'rgba(0,0,0,.6)',
                            'rgba(247,185,85,.12)', '#1a1408', 'rgb(20,22,26)', 'hsl(40,90%,65%)')
           for r in ('bg', 'text', 'border', 'shadow', 'var')]
js = r'''
const fs=require('fs'),vm=require('vm');
const attrs={};const root={getAttribute:k=>attrs[k]||null,setAttribute:(k,v)=>{attrs[k]=v},removeAttribute:k=>{delete attrs[k]}};
const ctx={window:{},document:{documentElement:root,cookie:'',readyState:'complete',addEventListener(){},querySelector:()=>null,
  querySelectorAll:()=>[],getElementById:()=>null,head:null,body:null},localStorage:{getItem:()=>null,setItem(){}},
  MutationObserver:function(){this.observe=function(){};this.disconnect=function(){}},getComputedStyle:()=>({getPropertyValue:()=>''}),
  CustomEvent:function(){},WeakMap,location:{protocol:'https:'},setTimeout,SVGElement:function(){}};
ctx.window=ctx;vm.createContext(ctx);vm.runInContext(fs.readFileSync('static/theme-light.js','utf8'),ctx);
const V=JSON.parse(process.argv[1]);console.log(JSON.stringify(V.map(([c,r])=>ctx.OrcThemeMap.mapToken(c,r))));
'''
res = subprocess.run(['node', '-e', js, json.dumps(VECTORS)], cwd=ROOT, capture_output=True, text=True, timeout=30)
js_out = json.loads(res.stdout) if res.returncode == 0 and res.stdout.strip() else None
def close(a, b):
    pa, pb = t.parse_color(a), t.parse_color(b)
    return pa and pb and all(abs(x - y) <= 1.5 for x, y in zip(pa[:3], pb[:3])) and abs(pa[3] - pb[3]) < 0.01
mismatch = [(c, r, t.map_token(c, r), j) for (c, r), j in zip(VECTORS, js_out or [])
            if not close(t.map_token(c, r), j)]
check('the JavaScript runtime maps colours exactly like the server (%d cases)' % len(VECTORS),
      js_out is not None and not mismatch)
if mismatch:
    print('   ', mismatch[:5], res.stderr[-300:])

# ── pages ──
page = ('<!doctype html><html lang="en"><head><link rel="stylesheet" href="/static/navbar.css?v=3">'
        '<link rel="stylesheet" href="/static/home-mobile.css?v=1" media="(max-width:768px)">'
        '<style>.x{color:#eef1f5}</style></head><body></body></html>')
light, dark = t.transform_html(page, True, '9'), t.transform_html(page, False, '9')
check('a light page is light from the server: data-theme on <html>, no dark flash', '<html lang="en" data-theme="light">' in light)
check('...and a dark page carries no theme and nothing extra to download (no companions)',
      '<html lang="en">' in dark and '/theme-light/' not in dark and 'data-oa-light="1">html' not in dark
      and '/static/theme-light.js' in dark)
check('every stylesheet gets its light companion right after it, media kept',
      '<link rel="stylesheet" href="/theme-light/navbar.css?v=9" data-oa-light-for="navbar.css">' in light
      and 'href="/theme-light/home-mobile.css?v=9" data-oa-light-for="home-mobile.css" media="(max-width:768px)"' in light
      and light.index('/static/navbar.css') < light.index('/theme-light/navbar.css'))
check('every <style> block gets its companion block',
      '<style data-oa-lt="1">.x{color:#eef1f5}</style><style data-oa-light="1">html[data-theme="light"] .x{color:#0c0d0f}</style>' in light)
check('the runtime and base styles load first in <head>',
      light.index('/static/theme-light.js') < light.index('/static/navbar.css')
      and '/static/theme-light-base.css' in light)
check('transforming twice changes nothing', t.transform_html(light, True, '9') == light)

import app_entry  # noqa: E402
app = app_entry.app
c = app.test_client()
r = c.get('/theme-light/navbar.css?v=1')
body = r.get_data(as_text=True)
check('the companion stylesheet is served, scoped to light, cached by version',
      r.status_code == 200 and r.mimetype == 'text/css' and body.startswith('html[data-theme="light"]')
      and 'immutable' in r.headers.get('Cache-Control', ''))
check('...and only for real stylesheets in /static',
      c.get('/theme-light/../dashboard.py').status_code == 404 and c.get('/theme-light/nope.css').status_code == 404)
c.set_cookie('oa_theme', 'light', domain='orcagent.fun')
html = c.get('/info', base_url='https://orcagent.fun').get_data(as_text=True)
check('the oa_theme cookie makes the server send the page light', 'data-theme="light"' in html and '/theme-light/' in html)

# ── the switch ──
d = app_entry._dashboard
nav = d._navbar_more_items_html()
check('the navbar menu has a Light mode switch', 'data-oa-theme-switch' in nav and 'role="switch"' in nav and 'Light mode' in nav)
check('the phone menu shows the same switch, not a proxy for it',
      "src.hasAttribute('data-oa-theme-switch')" in read('static', 'mobile-bottom-nav.js'))
check('Settings has a Light mode toggle', 'id="pref-theme-light"' in read('dashboard.html')
      and "OrcTheme.set(this.checked?'light':'dark')" in read('dashboard.html'))
rt = read('static', 'theme-light.js')
check('the choice is remembered on this device (cookie for the server, storage for the page)',
      "document.cookie='oa_theme='+theme" in rt and "localStorage.setItem('oa_theme',theme)" in rt)
check('a QR code keeps its dark-on-white colours, or it would not scan',
      'data-oa-keep' in read('templates', 'wallet.html') and "el.closest('[data-oa-keep]')" in rt)
check('switching back restores every colour the runtime changed, without a reload', 'function restoreAll()' in rt and 'stopRuntime()' in rt)
raise SystemExit(0 if all(checks) else 1)
