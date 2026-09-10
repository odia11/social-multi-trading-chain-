"""The buy screen is a full sheet with its own keypad, and it must not have
changed what happens when you press Buy.

WHY IT CHANGED
Buying was a number input tucked inside the token card. On a phone, focusing
it slid the OS keyboard up over the price, the 24h move and the balance --
every figure the person was deciding on -- at the exact moment they were
deciding. The sheet takes the whole screen instead: token at the top, the
amount enormous in the middle, a keypad that belongs to the page.

WHAT MUST NOT HAVE CHANGED
The trade. The sheet hands its own footer the ids confirmBuy() already looks
for (pt-buy-panel-N / pt-buy-amt-N / pt-buy-msg-N / pt-quote-N) and puts the
index on the button, so quotes, the three EVM routes, the Solana route and
the auto-bridge polling all run exactly as before. Nothing about this is a
new way to spend money -- it is a new way to look at one.

THREE THINGS REAL-BROWSER TESTING CAUGHT, none of which reading the code
would have shown:

  · the sheet opened UNDER the sticky navbar (z-index 120 vs 200), so the
    navbar's avatar swallowed clicks meant for the sheet's close button and
    the sheet could not be closed at all;
  · onclick="closeBuySheet()" in the template threw ReferenceError, because
    everything in live-market-pro.js lives inside an IIFE and that function
    is not a global;
  · the price rendered underneath the absolutely-positioned close button,
    showing "$0.001..." with the digits that matter hidden.

So the checks below run the real page in a real browser rather than reading
the source for reassurance.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

REPO = '/home/user/Orc-agent-Solana-chain-'
HTML = open(REPO + '/templates/live_market_pro.html', encoding='utf-8').read()
JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def no_comments(css):
    return re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)


HTML_NC = no_comments(HTML)

# ── 1. the buy path is reused, not reimplemented ─────────────────────────
check('the sheet carries the ids confirmBuy() already reaches for, so the '
      'trade runs through the same code it always did',
      "'pt-buy-panel-'+idx" in JS and "'pt-buy-amt-'+idx" in JS
      and "'pt-buy-msg-'+idx" in JS and "'pt-quote-'+idx" in JS)
check('...handed over on open and given back on close, so the next token '
      'reuses the same sheet',
      '_sheetBindIds' in JS and '_sheetUnbindIds' in JS)
check('the confirm button still carries data-action="confirm-buy", the hook '
      'the existing delegated handler dispatches on',
      'data-action="confirm-buy"' in HTML_NC)
check('openBuyPanel still exists as the name every card Buy button calls',
      re.search(r'function openBuyPanel\(idx\)\s*\{', JS) is not None)
check('...and it opens the sheet rather than building the old in-card panel',
      'openBuySheet(idx);' in JS)
check('no second buy request was invented — the sheet sends nothing itself',
      'instant-trade' not in JS.split('function openBuySheet')[1].split('function closeBuySheet')[0])

# ── 2. closing it, and the two ways that broke ───────────────────────────
check('the sheet sits above the navbar (200) and its dropdowns (280) — under '
      'them, the navbar swallowed the clicks meant for its close button',
      re.search(r'\.pt-sheet\{[^}]*z-index:(\d+)', HTML_NC)
      and int(re.search(r'\.pt-sheet\{[^}]*z-index:(\d+)', HTML_NC).group(1)) > 280)
check('the scrim sits just under the sheet, not over it',
      re.search(r'\.pt-sheet-scrim\{[^}]*z-index:(\d+)', HTML_NC)
      and int(re.search(r'\.pt-sheet-scrim\{[^}]*z-index:(\d+)', HTML_NC).group(1))
          < int(re.search(r'\.pt-sheet\{[^}]*z-index:(\d+)', HTML_NC).group(1)))
check('closing is wired through the delegated handler, not an inline onclick '
      '— this file is an IIFE, so closeBuySheet is not a global and an '
      'inline onclick threw ReferenceError',
      'onclick="closeBuySheet' not in HTML
      and 'data-action="close-sheet"' in HTML_NC
      and '[data-action="close-sheet"]' in JS)
check('the header leaves room for the close button, which is positioned in '
      'the same corner and rendered on top of the price',
      re.search(r'\.pt-sheet-hd\{[^}]*padding-right:\d+px', HTML_NC) is not None)

# ── 3. the minimum comes from the server ─────────────────────────────────
check('the minimum spend is handed to the page by the server rather than '
      'written into the JS again, so it cannot drift from what the trade '
      'routes enforce',
      'PT_MIN_BUY_USDC = {{ min_buy_usdc' in HTML
      and 'min_buy_usdc=SOLANA_MIN_SPEND_USDC' in open(REPO + '/dashboard.py', encoding='utf-8').read())
check('the sheet reads that value rather than a literal of its own',
      'PT_MIN_BUY_USDC' in JS and not re.search(r'amt\s*<\s*[12](\.0)?\b', JS))

# ── 4. the whole thing, in a real browser ────────────────────────────────
PORT = 5091
DATA = tempfile.mkdtemp()
server = subprocess.Popen(
    [sys.executable, '-c',
     'import os;os.environ.update({"DATA_DIR":%r,"SECRET_KEY":"x"*32,'
     '"ENCRYPTION_KEY":"K"*43+"=","DEV":"1"});'
     'import sys;sys.path.insert(0,%r);import dashboard as d;'
     'd.app.run(host="127.0.0.1",port=%d,debug=False,use_reloader=False,threaded=True)'
     % (DATA, REPO, PORT)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

DRIVER = r'''
import asyncio, json, sys
from playwright.async_api import async_playwright
PORT = %d
TOK = {"mint":"M"+"1"*39,"symbol":"UPONLY","name":"Up Only","chain":"bsc",
  "pair_address":"P1","image_url":"","price_usd":0.0013,"market_cap":1300000,
  "liquidity_usd":90000,"volume_24h":200000,"buys_24h":50,"sells_24h":20,
  "price_change_24h":180.51,"pair_created_at":None,"verified_socials":False,"score":4}
BAL = {"ok":True,"solana_usdc":0.0,"total_usdc":12.4,
       "evm_chains":{"bsc":12.4,"base":0,"arbitrum":0,"polygon":0,"robinhood":0}}
async def main():
    out = {}
    async with async_playwright() as p:
        b = await p.chromium.launch(
            executable_path='/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
            args=['--no-sandbox'])
        ctx = await b.new_context(viewport={'width':390,'height':844},
                                  is_mobile=True, has_touch=True)
        page = await ctx.new_page()
        errs = []
        page.on('pageerror', lambda e: errs.append(str(e)))
        await page.route('**/api/market/scanner*', lambda r: r.fulfill(
            status=200, content_type='application/json',
            body=json.dumps({"ok":True,"counts":{},"tokens":[TOK]})))
        await page.route('**/api/wallet/usdc-summary*', lambda r: r.fulfill(
            status=200, content_type='application/json', body=json.dumps(BAL)))
        await page.goto('http://127.0.0.1:%%d/live-market' %% PORT,
                        wait_until='domcontentloaded')
        await page.wait_for_selector('.pt-card', timeout=15000)
        await page.click('[data-action="buy-open"]')
        await page.wait_for_timeout(900)
        g = "i => document.getElementById(i)"
        out['opened'] = await page.evaluate(
            "document.getElementById('pt-sheet').classList.contains('open')")
        # the close button must actually be reachable, not under the navbar
        out['close_hittable'] = await page.evaluate("""() => {
            const b = document.querySelector('.pt-sheet-close');
            const r = b.getBoundingClientRect();
            const hit = document.elementFromPoint(r.x+r.width/2, r.y+r.height/2);
            return !!(hit && hit.closest('[data-action="close-sheet"]'));
        }""")
        # the price must not be hidden under it either
        out['price_clear'] = await page.evaluate("""() => {
            const p = document.getElementById('pt-sheet-price').getBoundingClientRect();
            const c = document.querySelector('.pt-sheet-close').getBoundingClientRect();
            return p.right <= c.left + 1;
        }""")
        for k in ['0','.','1','5']:
            await page.click('#pt-keys .pt-key[data-k="%%s"]' %% k)
            await page.wait_for_timeout(90)
        out['typed'] = await page.evaluate("""() => ({
            shown: document.getElementById('pt-sheet-amt').textContent,
            hidden: document.querySelector('#pt-sheet input[type=hidden]').value,
            label: document.getElementById('pt-sheet-go').textContent,
            disabled: document.getElementById('pt-sheet-go').disabled })""")
        await page.click('.pt-pct[data-pct="100"]')
        await page.wait_for_timeout(300)
        out['max'] = await page.evaluate("""() => ({
            hidden: document.querySelector('#pt-sheet input[type=hidden]').value,
            disabled: document.getElementById('pt-sheet-go').disabled,
            avail: document.getElementById('pt-sheet-avail').textContent })""")
        await page.click('.pt-sheet-close')
        await page.wait_for_timeout(400)
        out['closed'] = not await page.evaluate(
            "document.getElementById('pt-sheet').classList.contains('open')")
        out['ids_returned'] = await page.evaluate(
            "!!document.getElementById('pt-buy-amt-sheet')")
        out['errors'] = errs[:3]
        await b.close()
    print('@@' + json.dumps(out))
asyncio.run(main())
''' % PORT

for _ in range(40):
    try:
        import urllib.request
        urllib.request.urlopen('http://127.0.0.1:%d/live-market' % PORT, timeout=2)
        break
    except Exception:
        time.sleep(1)

try:
    r = subprocess.run([sys.executable, '-c', DRIVER], capture_output=True,
                       text=True, timeout=240)
    line = [l for l in r.stdout.splitlines() if l.startswith('@@')]
    B = json.loads(line[-1][2:]) if line else {}
    assert B, (r.stdout[-1500:] + r.stderr[-1500:])
finally:
    server.terminate()

check('BROWSER: pressing Buy on a card opens the sheet', B.get('opened'))
check('BROWSER: the close button is actually clickable — not covered by the '
      'navbar, which is how it shipped the first time', B.get('close_hittable'))
check('BROWSER: the price is not hidden under the close button',
      B.get('price_clear'))
check('BROWSER: the keypad types into the amount', B['typed']['shown'] == '$0.15')
check('BROWSER: ...and into the hidden field confirmBuy() reads, so what is '
      'on screen is what gets bought', B['typed']['hidden'] == '0.15')
check('BROWSER: below the minimum the button says so instead of failing '
      'after a round trip',
      B['typed']['disabled'] and 'minimum' in B['typed']['label'])
check('BROWSER: Max fills in the whole balance and never more',
      float(B['max']['hidden']) == 12.4 and not B['max']['disabled'])
check('BROWSER: the balance is shown to the cent, not rounded to "$12" while '
      'Max fills in 12.40', '$12.40' in B['max']['avail'])
check('BROWSER: it closes', B.get('closed'))
check('BROWSER: ...and gives the ids back, so the next token can use it',
      B.get('ids_returned'))
check('BROWSER: no JavaScript errors on the whole journey',
      not B.get('errors'))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
