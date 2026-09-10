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
# The tap hook is gone on purpose. A tap is what a pocket, a mis-scroll or
# a fat thumb produces by accident, and these spends are irreversible.
check('a TAP cannot buy any more — the control carries no '
      'data-action="confirm-buy", so only a completed slide reaches '
      'confirmBuy()',
      'data-action="confirm-buy"' not in HTML_NC)
check('...and a completed slide is what calls it',
      re.search(r'_slideRelease[\s\S]*?confirmBuy\(idx\)', JS) is not None)
check('letting go before the end snaps back instead of confirming',
      '_slideReset();' in JS and '0.85' in JS)
check('selling goes through the same gesture, not the old two-tap arm whose '
      '3-second window made a stray tap sell',
      '_sellArmed' not in JS and 'handleSell(idx)' in JS)
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
check('there is no ✕ in the corner any more — a downward swipe dismisses it, '
      'which is both what every other sheet on the device answers to and '
      'reachable with the thumb already holding the phone',
      'pt-sheet-close' not in HTML)
check('the scrim still closes it, so a mouse has a way out too',
      'data-action="close-sheet"' in HTML_NC and '[data-action="close-sheet"]' in JS)
check('closing is wired through the delegated handler, not an inline onclick '
      '— this file is an IIFE, so closeBuySheet is not a global and an '
      'inline onclick threw ReferenceError',
      'onclick="closeBuySheet' not in HTML)
check('a downward drag only counts past a threshold, so a scroll or a stray '
      'touch does not dismiss a screen someone is using',
      'window.innerHeight * 0.25' in JS)
check('an upward drag does nothing', 'if(dy < 0) dy = 0;' in JS)
check('a drag that starts on the keypad, the slider or the percentages '
      'belongs to those, not to the sheet',
      "closest('#pt-keys, .pt-slide, .pt-sheet-pcts')" in JS)

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
        out['no_close_btn'] = not await page.evaluate(
            "!!document.querySelector('.pt-sheet-close')")
        # the label must be readable: it also carries .pt-buy-confirm, whose
        # old button styling painted amber text on an amber ground
        out['label_readable'] = await page.evaluate("""() => {
            const l = document.getElementById('pt-sheet-go');
            const s = getComputedStyle(l);
            return s.backgroundColor === 'rgba(0, 0, 0, 0)' && s.color !== s.backgroundColor;
        }""")
        for k in ['0','.','1','5']:
            await page.click('#pt-keys .pt-key[data-k="%%s"]' %% k)
            await page.wait_for_timeout(90)
        out['typed'] = await page.evaluate("""() => ({
            shown: document.getElementById('pt-sheet-amt').textContent,
            hidden: document.querySelector('#pt-sheet input[type=hidden]').value,
            label: document.getElementById('pt-sheet-go').textContent,
            ready: document.getElementById('pt-slide').classList.contains('ready') })""")
        await page.click('.pt-pct[data-pct="100"]')
        await page.wait_for_timeout(300)
        out['max'] = await page.evaluate("""() => ({
            hidden: document.querySelector('#pt-sheet input[type=hidden]').value,
            ready: document.getElementById('pt-slide').classList.contains('ready'),
            avail: document.getElementById('pt-sheet-avail').textContent })""")
        # A half slide must buy nothing. This is the property the whole
        # gesture exists for.
        out['traded'] = []
        async def rec(route):
            out['traded'].append(route.request.url.split('/api')[1])
            await route.fulfill(status=200, content_type='application/json',
                                body=json.dumps({"ok":True,"success":True,"sell_executed":True}))
        await page.route('**/api/bsc/trade/**', rec)
        async def slide(frac):
            box = await page.evaluate("""() => {
                const k=document.getElementById('pt-slide-knob').getBoundingClientRect();
                const w=document.getElementById('pt-slide').getBoundingClientRect();
                return {kx:k.x+k.width/2, ky:k.y+k.height/2, travel:w.width-k.width-10}; }""")
            await page.mouse.move(box['kx'], box['ky']); await page.mouse.down()
            for i in range(12):
                await page.mouse.move(box['kx']+box['travel']*frac*(i+1)/12, box['ky'])
                await page.wait_for_timeout(15)
            await page.mouse.up(); await page.wait_for_timeout(350)
        await slide(0.4)
        out['half_slide_traded'] = list(out['traded'])
        out['knob_snapped_back'] = await page.evaluate(
            "!document.getElementById('pt-slide-knob').style.transform")
        await slide(1.0)
        out['full_slide_traded'] = list(out['traded'])

        # a downward swipe dismisses it; a short one does not
        async def swipe(dy):
            await page.evaluate("""dy => {
                const el=document.getElementById('pt-sheet');
                const mk=(n,cy)=>new TouchEvent(n,{bubbles:true,cancelable:true,
                  touches:n==='touchend'?[]:[new Touch({identifier:1,target:el,clientX:195,clientY:cy})],
                  changedTouches:[new Touch({identifier:1,target:el,clientX:195,clientY:cy})]});
                el.dispatchEvent(mk('touchstart',300));
                for(let i=1;i<=8;i++) el.dispatchEvent(mk('touchmove',300+dy*i/8));
                el.dispatchEvent(mk('touchend',300+dy));
            }""", dy)
            await page.wait_for_timeout(400)
        await page.evaluate("document.getElementById('pt-sheet').classList.add('open')")
        await swipe(60)
        out['short_swipe_kept_open'] = await page.evaluate(
            "document.getElementById('pt-sheet').classList.contains('open')")
        await swipe(240)
        out['long_swipe_closed'] = not await page.evaluate(
            "document.getElementById('pt-sheet').classList.contains('open')")

        # selling opens the same sheet, in sell mode
        await page.click('[data-action="sell"]')
        await page.wait_for_timeout(700)
        out['sell'] = await page.evaluate("""() => ({
            mode: document.getElementById('pt-sheet').classList.contains('sell-mode'),
            keypadHidden: getComputedStyle(document.getElementById('pt-keys')).display === 'none',
            amt: document.getElementById('pt-sheet-amt').textContent,
            label: document.getElementById('pt-sheet-go').textContent,
            red: document.getElementById('pt-slide').classList.contains('sell') })""")
        out['traded'].clear()
        await slide(1.0)
        out['sell_traded'] = list(out['traded'])

        await page.evaluate("document.getElementById('pt-sheet-scrim').click()")
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
check('BROWSER: no ✕ is rendered', B.get('no_close_btn'))
check('BROWSER: the slider label is readable — it also carries '
      '.pt-buy-confirm, the old button style, which painted amber text on '
      'an amber ground until that was scoped away',
      B.get('label_readable'))
check('BROWSER: the keypad types into the amount', B['typed']['shown'] == '$0.15')
check('BROWSER: ...and into the hidden field confirmBuy() reads, so what is '
      'on screen is what gets bought', B['typed']['hidden'] == '0.15')
check('BROWSER: below the minimum the control says so instead of failing '
      'after a round trip', 'minimum' in B['typed']['label'])
check('BROWSER: ...and is not armed, so it cannot be slid', not B['typed']['ready'])
check('BROWSER: Max fills in the whole balance and never more',
      float(B['max']['hidden']) == 12.4 and B['max']['ready'])
check('BROWSER: the balance is shown to the cent, not rounded to "$12" while '
      'Max fills in 12.40', '$12.40' in B['max']['avail'])
check('BROWSER: it closes', B.get('closed'))
check('BROWSER: ...and gives the ids back, so the next token can use it',
      B.get('ids_returned'))
check('BROWSER: a HALF slide buys nothing — the point of the gesture',
      B.get('half_slide_traded') == [])
check('BROWSER: ...and the knob snaps back rather than sitting half-way',
      B.get('knob_snapped_back'))
check('BROWSER: a COMPLETED slide buys, once',
      B.get('full_slide_traded') == ['/bsc/trade/buy'])
check('BROWSER: a short downward drag does not dismiss the sheet',
      B.get('short_swipe_kept_open'))
check('BROWSER: a real downward swipe does, returning to Live Market',
      B.get('long_swipe_closed'))
check('BROWSER: Sell opens the same sheet in sell mode', B['sell']['mode'])
check('BROWSER: ...with no keypad, since the server closes the whole tracked '
      'position and there is no amount to ask for', B['sell']['keypadHidden'])
check('BROWSER: ...saying so plainly', B['sell']['amt'] == 'Sell all')
check('BROWSER: ...in red, and asking for the same gesture',
      B['sell']['red'] and 'Slide to sell' in B['sell']['label'])
check('BROWSER: a completed slide sells', B.get('sell_traded') == ['/bsc/trade/sell'])
check('BROWSER: no JavaScript errors on the whole journey',
      not B.get('errors'))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
