"""The app carries no dead pages, and its tests really run.

- Every template is rendered by a route (or included by one). The old
  Live Market, the standalone token page and the old Settings page were
  unrouted leftovers, along with token-card.js/.css they alone loaded and a
  deep-link "fix" that looked for Live Market cards that no longer exist.
- Token cards in DMs and shared trades open the token in the current Live
  Market (?mint=...&profile=1), and the ?addr= links already sent still do.
- Surge Alerts can be switched on again: its toggle lived only on the
  unrouted Settings page.
- No test points at a checkout path that does not exist (61 of them did, so
  they failed before testing anything), and no test writes files into the
  repository.
"""
import glob, os, re, subprocess
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

py = ''.join(read(p) for p in glob.glob(os.path.join(ROOT, '*.py')))
templates = sorted(os.path.basename(t) for t in glob.glob(os.path.join(ROOT, 'templates', '*.html')))
tpl_src = ''.join(read('templates', t) for t in templates)
unrendered = [t for t in templates
              if ("'%s'" % t) not in py and ('"%s"' % t) not in py
              and not re.search(r"{%%\s*(include|extends)\s+['\"]%s" % re.escape(t), tpl_src)]
check('every template is rendered by a route or included by one', not unrendered)
gone = ['templates/live_market.html', 'templates/token.html', 'templates/settings.html',
        'static/token-card.js', 'static/token-card.css', 'static/live-market-deeplink-fix.js',
        'live_market_deeplink_fix.py']
check('the unrouted pages and the files only they used are gone',
      not any(os.path.exists(os.path.join(ROOT, g)) for g in gone)
      and 'live_market_deeplink_fix' not in read('app_entry.py')
      and 'token-card.css' not in read('static', 'app-ux.js'))

lm = read('static', 'live-market-pro.js')
check('DM and shared-trade token cards open the token in the current Live Market',
      "'/live-market?mint='+encodeURIComponent(mint)+'&profile=1'" in read('static', 'messages-ui.js')
      and "'/live-market?mint='+encodeURIComponent(t.mint)+'&profile=1'" in read('static', 'shared-trade-card-v2.js'))
check('...and ?addr= links already sent still open that token',
      "var _qMint = _qs.get('mint') || _qs.get('addr');" in lm
      and "(_qs.get('addr') && !_qs.get('mint'))) _profileMint=_qMint;" in lm)

home = read('dashboard.html'); js = read('static', 'dashboard.js')
check('Surge Alerts can be switched on in Settings, and shows its saved state',
      'id="pref-surge" onchange="_savePref(\'surge_alerts\',this.checked)"' in home
      and "surge.checked =!!d.pref_surge_alerts" in js)

tests = glob.glob(os.path.join(ROOT, 'tests', '*.py')) + glob.glob(os.path.join(ROOT, 'tests', '*.js'))
bad_path = [os.path.basename(t) for t in tests if 'Orc-agent-Solana-' + 'chain-' in read(t)]
check('no test points at a checkout path that does not exist', not bad_path)
tracked = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True).stdout.split()
check('no test harness leftovers are tracked in the repository',
      not [f for f in tracked if re.fullmatch(r'_[a-z]{2}\.js', f)]
      and "open('_lh.js'" not in read('tests', 'test_post_links.py')
      and "open('_tl.js'" not in read('tests', 'test_token_lookup.py'))
raise SystemExit(0 if all(checks) else 1)
