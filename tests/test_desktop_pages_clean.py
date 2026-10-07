"""Desktop pages without visible errors (found by going through every page at
1280 and 1440 px).

- Portfolio threw "_loadBridgeHistory is not defined" (the function went with
  the Solana-only change, its call stayed), which stopped the rest of the
  script: Recent activity and manual trades never loaded.
- Home's Deposit showed the login wallet, not the trading wallet OrcAgent
  trades with, with a QR from a third-party service whose error handler threw.
  Deposit now opens Portfolio's deposit sheet (the trading wallet).
- Home (desktop): the bot card read "false open" with 0 positions; a fake
  "For You / Following" label and the old "Your bot is idle" card repeated
  what is already on the page; the sidebar brand ran "OrcAgentSOCIAL" together.
- Notifications: the list sat 640 px wide against the left edge under a
  full-width header; now one centred column.
- Calls: the LIVE pill sat on top of the banner slogan.
- Live Trades and Referrals did not load Geist, so the navbar fell back to a
  wider font there.
- Admin: a bare link above the navbar is now a menu item.
- Portfolio: "≈ 0.833333333 SOL" -> at most 4 decimals.
"""
import os, re, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: (ROOT.joinpath(*p)).read_text(encoding='utf-8')

wallet = read('templates', 'wallet.html')
calls_ = re.findall(r'^\s*(_[A-Za-z]\w*)\(\)\s*$', wallet, re.M)
undefined = [f for f in set(calls_) if not re.search(r'function\s+' + f + r'\s*\(', wallet)]
check('Portfolio calls no function that does not exist (it stopped Recent activity loading)', not undefined)
check('...the SOL equivalent shows at most 4 decimals', 'maximumFractionDigits:9' not in wallet
      and all('maximumFractionDigits:9' not in read('static', f) for f in ('approved-portfolio.js', 'portfolio-multichain.js')))

js = read('static', 'dashboard.js')
dep = js[js.index('function openDepositModal() {'):js.index('function closeDepositModal() {')]
check('Deposit opens the trading wallet deposit sheet, not the login wallet', "location.href = '/wallet#deposit'" in dep and 'phantomKey' not in dep)
check('...no third-party QR service anywhere', 'api.qrserver.com/v1' not in js)
import app_entry  # noqa: E402
r = app_entry.app.test_client().get('/deposit', base_url='https://orcagent.fun')
check('/deposit goes to Portfolio\'s deposit sheet', r.status_code in (301, 302) and r.headers['Location'].endswith('/wallet#deposit'))

hd = read('static', 'home-desktop.js')
fn = hd[hd.index('function buildBot(wrap){'):hd.index('function buildPortfolio(')]
check('Home bot card: 0 open positions reads "0 open", never "false open"',
      'd.open_positions!=null?Number(d.open_positions)' in fn and '(d.open_positions!=null&&d.open_positions)||' not in fn)
out = subprocess.run(['node', '-e', '''
var d={open_positions:0};var open=d?(d.open_positions!=null?Number(d.open_positions):(d.positions_open!=null?Number(d.positions_open):null)):null;
console.log(String(open)+' open')'''], capture_output=True, text=True).stdout.strip()
check('...(evaluated: ' + out + ')', out == '0 open')
check('no fake "For You / Following" label above the real feed tabs', 'addFeedLabel' not in hd)
hcss = read('static', 'home-desktop.css')
check('the old feed bot card is hidden next to the new one',
      'body.oa-home-desktop .feed-bot-card{display:none!important}' in hcss)
check('no second logo, bell or search on desktop Home: the navbar above already has them',
      'oa-desk-brand' not in hd and 'oa-home-head-btn' not in hd
      and '#right-rail .rr-search{display:none}' in read('dashboard.html'))

ntf = read('templates', 'notifications.html')
check('Notifications: header and list share one centred column',
      '.ntf-body{max-width:720px;margin:0 auto' in ntf and '.ntf-header>*{max-width:668px;margin-left:auto;margin-right:auto}' in ntf)
calls = read('templates', 'calls.html')
check('Calls: LIVE sits in the banner corner on desktop, off the slogan',
      '@media(min-width:768px){.calls-hero .page-header-row{position:static}.calls-hero .live-badge{position:absolute;top:14px;right:16px' in calls)
for t in ('live_trades.html', 'referrals.html'):
    check(t + ' loads Geist for the shared navbar', 'family=Geist:' in read('templates', t))
adm = read('templates', 'admin.html')
check('Admin: no bare link above the navbar; it is a menu item',
      '<body>\n{{ navbar_html' in adm and 'id="nav-rewards-review" href="/admin/rewards"' in adm)
raise SystemExit(0 if all(checks) else 1)
