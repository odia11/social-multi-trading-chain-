"""The phone buy/sell sheet stays neat when "Fees & costs" is opened.

Seen on an iPhone (390x844): the quick-amount row drew its old segmented
track -- background and border -- edge to edge behind the four tiles, so a
bordered box ran off both sides of the screen. And opening "Fees & costs"
made the footer taller while the keypad held a fixed height: the only part
that could shrink was the amount, which was squeezed and clipped -- "$0.51"
pressed against the Buy/Sell switch and the 24h move / liquidity / volume
row cut off under the percentage buttons.

Now the amount never shrinks below what it shows, the keypad's keys get
shorter instead, and if a small phone still runs out of room the sheet
scrolls rather than hiding the slide-to-confirm. Scrolling it back up
used to count as "swipe down to close" and shut the sheet; closing now only
starts when the sheet is at the top.
"""
import os, re, sys
ROOT = os.path.join(os.path.dirname(__file__), '..')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()

css = read('static', 'live-market-redesign.css')
v4 = css[css.index('Mobile execution sheet v4'):css.index('Mobile token card v5')]
def rule(sel_re):
    m = re.search(sel_re + r'\{([^}]*)\}', v4)
    return re.sub(r'\s+', '', m.group(1)) if m else ''

mid = rule(r'body\.oa-live-v2 \.pt-sheet-mid')
check('the amount never shrinks below what it shows (it was squeezed and clipped)',
      'flex:10auto!important' in mid and 'overflow:visible!important' in mid)
pcts = rule(r'body\.oa-live-v2 \.pt-sheet-pcts')
check('the quick amounts are four tiles inside the margins, no full-width bordered track behind them',
      'background:transparent!important' in pcts and 'border:0!important' in pcts and 'padding:018px9px!important' in pcts)
keys = rule(r'body\.oa-live-v2 #pt-keys,body\.oa-live-v2 \.pt-keys')
check('the keypad gives way instead: shorter keys, never overlapping',
      'grid-template-rows:repeat(4,minmax(0,1fr))!important' in keys and 'flex:01clamp(' in keys)
key = rule(r'body\.oa-live-v2 \.pt-key')
check('...a key has no fixed minimum that would push the keypad over the amount', 'min-height:0!important' in key)
sheet = rule(r'body\.oa-live-v2 \.pt-sheet')
check('on a small phone the sheet scrolls rather than cutting off the slide-to-confirm',
      'overflow-y:auto!important' in sheet and 'overflow:hidden!important' not in sheet)
fees = rule(r'body\.oa-live-v2 \.pt-fees-sell')
check('the sale costs read as labelled lines, not a block of monospace', 'Geist' in fees)
js = read('static', 'live-market-pro.js')
check('...with short values that fit a phone', "'% of the sale</span></div>'" in js
      and 'of what the sale returns' not in js)
drag = js[js.index('(function bindSheetDrag(){'):js.index("document.addEventListener('touchcancel',end);", js.index('(function bindSheetDrag(){'))]
check('scrolling the sheet back up never closes it: swipe-to-close only starts at the top',
      'if(!sheet || sheet.scrollTop > 0) return;' in drag)
check('...and a drag that turns into a scroll stops moving the sheet',
      "if(sh.scrollTop > 0){" in drag and "sh.style.transform = '';" in drag)
for f in ('app_performance.py', 'static/navbar.js', 'static/app-ux.js'):
    check(f'phones fetch the new stylesheet ({f})', 'live-market-redesign.css?v=9' in read(*f.split('/')))
raise SystemExit(0 if all(checks) else 1)
