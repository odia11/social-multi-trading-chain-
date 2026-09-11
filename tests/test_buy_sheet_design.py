"""The buy screen had the shape every meme-coin buy screen has.

WHAT WAS WRONG WITH IT
One giant number centred in a black void, four grey pills, bare digits
painted straight onto the background, an amber bar at the bottom. It was a
recognisable copy of somebody else's screen, and the layout was doing real
damage on its own terms: the balance -- the figure that decides whether the
amount is even possible -- sat at the very bottom in grey, far from the
amount it constrains, and roughly a third of the screen was empty.

WHAT IT IS NOW
One surface carrying the whole decision: what the number means, the number,
the balance it is measured against, and what it converts into. Quick amounts
are a single segmented track rather than four loose pills, because they are
four answers to one question. Keys have faces, so there is something to aim
at. The slide track is a groove the knob travels along.

WHAT MUST NOT HAVE CHANGED
The trade. Every id confirmBuy(), handleSell() and scheduleQuote() reach
for is still on the element they expect, so the routes run exactly as they
did. That is asserted in test_buy_sheet.py, in a real browser, and this
file does not restate it -- it covers the things a screenshot would show
and a route test would not.

ACCESSIBILITY
This screen spends money and had none. Every control now says what it is
and shows where the focus is; the amount and the balance are readable
rather than grey-on-black; someone who has asked for less motion gets a
steady bar instead of a moving one; and the confirm gesture is reachable
from a keyboard -- by walking the knob across with the arrow keys, which
takes as many deliberate actions as a slide does. It used to confirm on a
single press of Enter, which is exactly the one accidental action the whole
control exists to prevent, just moved off the touchscreen.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
HTML = open(REPO + '/templates/live_market_pro.html', encoding='utf-8').read()
JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()
CSS = re.sub(r'/\*.*?\*/', '', HTML, flags=re.DOTALL)

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def rule(sel):
    # Anchored to the start of a rule, or ".pt-key" would match inside
    # ".pt-keys .pt-key" and read the wrong declaration block.
    m = re.search(r'(?:^|[\n};])\s*' + re.escape(sel) + r'\{([^}]*)\}', CSS, re.M)
    return m.group(1) if m else ''


# ── 1. the decision lives on one surface ─────────────────────────────────
check('the amount, what it means, what it buys and the balance sit on one '
      'ticket rather than floating separately down an empty screen',
      '<div class="pt-ticket">' in HTML
      and 'pt-ticket-top' in HTML and 'pt-ticket-get' in HTML)
check('...which is a real surface, with its own ground and edge',
      'background:var(--sheet-tile)' in rule('.pt-ticket')
      and 'border:1px solid var(--sheet-line)' in rule('.pt-ticket'))
# The balance decides whether the amount is possible at all. It used to be
# the last line before the button, in grey, as far from the amount as the
# screen allowed.
check('the balance is level with the amount it constrains, inside the '
      'ticket, not stranded in the footer',
      re.search(r'pt-ticket-top[\s\S]*?id="pt-sheet-avail"[\s\S]*?'
                r'</div>\s*<div class="pt-sheet-amt', HTML) is not None)
check('...and the footer no longer carries a balance row of its own',
      'class="pt-sheet-avail"' not in HTML)
check('what you get reads as a conversion, with an arrow saying which way '
      'it runs, rather than as a grey caption',
      'pt-ticket-arrow' in HTML
      and 'color:var(--green)' in rule('.pt-sheet-get'))

# ── 2. it is not the same screen as the one it was compared to ───────────
check('the amount is set against the ticket\'s own edge rather than centred '
      'in open space -- the single strongest cue of the layout it was '
      'accused of copying',
      'align-items:center' not in rule('.pt-sheet-mid')
      and 'flex-direction:column' in rule('.pt-ticket'))
check('the quick amounts are one segmented track, not four detached pills',
      'overflow:hidden' in rule('.pt-sheet-pcts')
      and 'border-left:1px solid var(--sheet-line)' in rule('.pt-pct')
      and 'border:none' in rule('.pt-pct'))
check('the keys have faces, so there is something to aim at instead of a '
      'glyph painted on the background',
      'background:var(--sheet-key)' in rule('.pt-key')
      and 'border:1px solid var(--sheet-line)' in rule('.pt-key'))
check('the slide track is recessed -- a groove the knob travels along, '
      'which is what the gesture is',
      'inset' in rule('.pt-slide'))
check('the knob is a disc that travels, not a block that slides',
      'border-radius:50%' in rule('.pt-slide-knob'))
check('the screen has a horizon rather than being flat black',
      'radial-gradient' in rule('.pt-sheet'))
check('the token art is not cropped into a circle — it is square wherever '
      'it comes from', 'border-radius:13px' in rule('.pt-sheet-img,.pt-sheet-img-ph'))

# ── 3. the empty third of the screen ─────────────────────────────────────
check('spare height on a tall phone goes into bigger keys rather than into '
      'a void around the number',
      'flex:1 1 auto' in rule('.pt-keys') and 'max-height:' in rule('.pt-keys'))
check('...and the ticket breathes with the screen instead of holding one '
      'fixed padding at every height',
      'vh' in rule('.pt-ticket'))
# Selling hides the keypad and the percentages, which used to leave two
# thirds of the screen empty above a single sentence.
check('the sell screen fills the room the keypad leaves with the three '
      'readings a sell decision turns on',
      'pt-ticket-stats' in HTML and 'pt-tstat-v' in HTML)
check('...read from the same token the card shows, not a second lookup that '
      'could disagree with it',
      re.search(r"pt-sheet-stats'\)\.innerHTML[\s\S]{0,400}t\.liquidity_usd", JS)
      is not None)
check('...and they are only there in sell mode, where there is room',
      '.pt-ticket-stats{display:none}' in CSS
      and '.pt-sheet.sell-mode .pt-ticket-stats{display:grid' in CSS)
check('the sell ticket sits within reach of the thumb rather than floating '
      'in the middle of an empty screen',
      'justify-content:flex-end' in rule('.pt-sheet.sell-mode .pt-sheet-mid'))

# ── 4. accessibility, on a screen that spends money ──────────────────────
check('focus is visible on every control in the sheet, so it can be used '
      'without a touchscreen at all',
      ':focus-visible' in CSS and 'outline:2px solid var(--accent)' in CSS)
# The row means two different things now -- shares of your balance to
# spend, shares of your position to close -- so the label is written when
# the sheet opens rather than sitting in the markup saying one of them.
check('the percentage buttons say what they do, not just what they read',
      "'Spend ' + pct + '% of your balance'" in JS
      and "'Spend your whole balance'" in JS)
check('...in whichever of the two things the row currently means',
      "'Sell ' + pct + '% of your position'" in JS
      and "'Sell your whole position'" in JS)
check('the keypad and the quick amounts are named groups',
      'aria-label="Amount keypad"' in HTML and 'aria-label="Quick amounts"' in HTML)
check('the result of a trade is announced rather than only drawn',
      re.search(r'id="pt-buy-msg-sheet"[^>]*aria-live="polite"', HTML)
      or re.search(r'aria-live="polite"[^>]*id="pt-buy-msg-sheet"', HTML))
check('someone who has asked for less motion still sees that it is working '
      '-- a steady bar rather than a moving one',
      'prefers-reduced-motion' in CSS
      and re.search(r'prefers-reduced-motion[\s\S]{0,240}animation:none', CSS))
# --muted2 on this ground is around 3.5:1, below the readable threshold for
# text this size. It was carrying the balance, the conversion and the
# slider's own label.
for sel, what in [('.pt-sheet-cap', 'what the number means'),
                  ('.pt-ticket-bal', 'the balance'),
                  ('.pt-slide .pt-slide-label', "the slider's own label")]:
    check(f'{what} is readable rather than the faintest grey available',
          'var(--muted2)' not in rule(sel))

# ── 5. the confirm gesture, from a keyboard ──────────────────────────────
check('a single Enter no longer buys — that was the one accidental action '
      'the slide exists to prevent, moved off the touchscreen',
      not re.search(r"e\.key === 'Enter'[\s\S]{0,200}_slideRelease\(\)", JS))
check('the knob walks across on the arrow keys instead, taking as many '
      'deliberate actions as a slide does',
      "e.key === 'ArrowRight'" in JS and 'KEY_STEPS' in JS
      and re.search(r'KEY_STEPS\s*=\s*([4-9]|\d\d)', JS))
check('...and can be walked back, or put back, without confirming',
      "e.key === 'ArrowLeft'" in JS and "e.key === 'Home' || e.key === 'Escape'" in JS)
check('...and it says so, so a keyboard user is told the gesture exists',
      'press the right arrow key' in HTML)

# ── 6. the routes are untouched ──────────────────────────────────────────
# Restated here only as a tripwire: if a redesign ever moves one of these
# off the element the trade code reaches for, this file fails next to the
# screenshot checks rather than leaving test_buy_sheet.py to find it alone.
for el in ['pt-buy-panel-sheet', 'pt-buy-amt-sheet', 'pt-buy-msg-sheet',
           'pt-quote-sheet', 'pt-sheet-amt', 'pt-sheet-get', 'pt-sheet-avail',
           'pt-sheet-cap-txt', 'pt-sheet-cur', 'pt-slide', 'pt-slide-fill',
           'pt-slide-knob', 'pt-sheet-go', 'pt-keys']:
    check(f'the redesign kept #{el}, which the trade code reaches for',
          'id="%s"' % el in HTML)
check('...and the footer the receipt prints into is still the element the '
      'ids are lent to', 'class="pt-sheet-ft" id="pt-buy-panel-sheet"' in HTML)
for k in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', '.', 'del']:
    check(f'the keypad still sends {k!r} under data-k',
          'data-k="%s"' % k in HTML)
for pct in ['10', '25', '50', '100']:
    check(f'the {pct}% button still carries data-pct',
          'data-pct="%s"' % pct in HTML)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
