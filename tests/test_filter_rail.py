"""The Live Market filter rail, on a phone.

WHAT IT WAS
Fifteen controls stacked open in a drawer: five sort rows, four safety
toggles, a slider, four age chips and a bot card. You had to scroll before
you could see what was even switched on, and every target was under the size
of a thumb — the sort rows about 36px, the toggle rows 33, the age chips 27,
and the switch itself 34x19. A row of things you aim at rather than press.

WHAT IT IS
Sort stays open, because that is the control you change constantly. Safety,
liquidity and age fold behind one row that says how many are active — folded
on a phone, open on desktop where the column has room. Every target is at
least 44px on a phone and unchanged on desktop, where a mouse does not need
it and the column is narrow.

The count on the collapsed row is not decoration. Hiding the filters without
it would be worse than the clutter: a feed narrowed by a forgotten toggle
looks exactly like a feed with nothing in it.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
HTML = open(REPO + '/templates/live_market_pro.html').read()
JS = open(REPO + '/static/live-market-pro.js').read()
CSS = re.search(r'<style>(.*?)</style>', HTML, re.S).group(1)
MOBILE = re.search(r'@media \(max-width: *900px\)(.*?)\n\}\n@media', CSS, re.S).group(1)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def _px(where, rule, prop):
    """One property of one rule, in px. Matched inside the rule body rather
    than immediately after the brace — the property is rarely first, and a
    test that assumes it is breaks on any reordering."""
    m = re.search(r'(?:^|[},\s])' + re.escape(rule) + r'\{([^}]*)\}', where)
    if not m:
        return None
    v = re.search(r'(?:^|;)\s*' + re.escape(prop) + r':\s*([0-9.]+)px', m.group(1))
    return float(v.group(1)) if v else None

def px(rule, prop):    return _px(MOBILE, rule, prop)
def desktop(rule, prop): return _px(CSS.split('@media')[0], rule, prop)


# ── everything is reachable with a thumb ──────────────────────────────────
for rule, prop, floor in [
    ('.pt-sort-row', 'min-height', 44),
    ('.pt-toggle-row', 'min-height', 44),
    ('.pt-age-chip', 'min-height', 44),
    ('.pt-adv-sum', 'min-height', 44),
    ('.pt-bot-btn', 'min-height', 44),
]:
    got = px(rule, prop)
    check(f'{rule} is at least {floor}px on a phone (is {got})',
          got is not None and got >= floor)
check('the switch is a thumb-sized target too, not a 34x19 sliver',
      px('.pt-switch', 'width') and px('.pt-switch', 'width') >= 44)
check('...and its knob keeps up with it, or the travel would look wrong',
      px('.pt-switch::after', 'width') == 20 and 'translateX(18px)' in MOBILE)
check('the liquidity thumb grows, since a 4px rail is nothing to grab',
      px('.pt-liq-slider::-webkit-slider-thumb', 'width') >= 20)
check('none of that leaks to desktop, where a mouse does not need it and the '
      'column is narrow — the base rules still carry their own smaller sizes',
      desktop('.pt-sort-row', 'padding') == 9
      and desktop('.pt-switch', 'width') == 34
      and desktop('.pt-age-chip', 'padding') == 6)

# ── the whole row is the button ───────────────────────────────────────────
check('a toggle row is a button, not a div wrapping a small one',
      '<button class="pt-toggle-row" data-filter=' in HTML)
check('...and the switch inside it is decoration that cannot swallow the tap',
      'pointer-events:none' in CSS
      and re.search(r'\.pt-switch\{[^}]*pointer-events:none', CSS))
check('...with the click handler reading the row',
      "closest('.pt-toggle-row')" in JS and "closest('.pt-switch')" not in JS)
check('...and the pressed state announced, since the switch is now only a '
      'picture of it', 'aria-pressed' in HTML and "setAttribute('aria-pressed'" in JS)

# ── less on screen at once ────────────────────────────────────────────────
check('the occasional settings fold behind one row', '<details class="pt-adv"' in HTML)
check('...open on desktop', '<details class="pt-adv" id="pt-adv" open>' in HTML)
check('...and folded on a phone, decided once at startup so reopening it is '
      'not undone by the next resize',
      "matchMedia('(max-width: 900px)')" in JS and 'advEl.open = false' in JS)
check('sort stays out of the fold — it is the one you change constantly',
      HTML.index('pt-sort-list') < HTML.index('<details class="pt-adv"'))
check('the drawer is TIGHTER between sections, so taller rows do not make it '
      'a longer scroll', 'gap:14px' in MOBILE)

# ── a hidden filter must never be a silent one ────────────────────────────
check('the collapsed row says how many filters are on',
      'function updateAdvCount' in JS and 'pt-adv-count' in HTML)
check('...counting the toggles, the age and the liquidity — all three can '
      'narrow a feed to nothing',
      '_FILTER_KEYS' in JS.split('function updateAdvCount')[1][:400]
      and "ST.age" in JS.split('function updateAdvCount')[1][:400]
      and 'ST.minLiquidity' in JS.split('function updateAdvCount')[1][:400])
check('...reading the state key that actually exists — minLiq was never a '
      'field, and a count that reads one silently ignores the slider',
      'ST.minLiq ' not in JS and 'ST.minLiq)' not in JS and 'ST.minLiquidity' in JS)
check('...refreshed by every control that can change it',
      JS.count('updateAdvCount()') >= 4)
check('...and showing nothing at all when nothing is on, so an untouched rail '
      'stays quiet', '.pt-adv-count:empty{display:none}' in CSS)

check('the stylesheet still has balanced braces',
      CSS.count('{') == CSS.count('}'))

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
