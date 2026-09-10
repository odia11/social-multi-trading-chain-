"""Tapping a token in the Surging Now strip must open it.

WHAT WAS HAPPENING
A regression from the swipe-smoothness change (259bf7a). To stop a
mouse-drag pan from also opening whatever card the cursor landed on, that
commit put this in templates/live_market_pro.html:

    .pt-surge-rail.pt-rail-dragging *{pointer-events:none}

...applied by a class that enableDragScroll() adds on mousedown and removes
on mouseup. Which reads as "only while dragging" -- but the browser
HIT-TESTS for mouseup before the mouseup handler gets to remove the class.
So on every press, however brief:

  · mousedown hit-tests with the class not yet set  -> target is the card
  · mouseup   hit-tests with the class still set    -> cards are unhittable,
                                                       target is the rail
  · a click's target is the common ancestor of those two -> the RAIL

and the delegated handler in live-market-pro.js, which dispatches on
e.target.closest('[data-action="open-surge"]'), matched nothing. Every tap
did nothing at all. The same rule covered .pt-story-rail and
.pt-trader-rail, so the story circles and trader circles went dead too.

Measured in a real browser before the fix: clicking a surge card logged
target DIV.pt-surge-rail, matched=False, while the card's computed
pointer-events read 'none' for as long as the button was down.

THE FIX
The pointer-events rule is gone; telling a drag from a tap is JS's job, and
JS can actually tell them apart. enableDragScroll() sets a swallowClick flag
on release only when the pointer moved more than 3px, and a capture-phase
click listener consumes it. mousedown clears the flag, so it can never
outlive its own gesture -- the earlier shape (adding a one-shot listener on
release) leaked when a drag ended off the rail and fired no click, leaving a
listener behind to eat the next genuine tap.

Verified in a real browser on both viewports: tap opens the token and routes
it into the Live Market feed, a real drag pans the rail and opens nothing,
and the tap straight after a drag works again.
"""
import re
import sys

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

# ── 1. nothing may make a rail's children unhittable ─────────────────────
check('no rule makes the drag rails\' children pointer-events:none -- that '
      'moves the click target up to the rail and the delegated handler '
      'stops matching',
      re.search(r'\.pt-rail-dragging\s*\*', HTML_NC) is None)

for rail in ('pt-story-rail', 'pt-surge-rail', 'pt-trader-rail'):
    rule = re.search(re.escape('.' + rail) + r'\.pt-rail-dragging[^{]*\{([^}]*)\}', HTML_NC)
    body = rule.group(1) if rule else ''
    check(f'.{rail}.pt-rail-dragging styles the cursor without disabling '
          'pointer events',
          'pointer-events' not in body)

drag_rule = re.search(r'([^{}]*\.pt-rail-dragging[^{]*)\{([^}]*)\}', HTML_NC)
check('the dragging class still does something useful (grabbing cursor, no '
      'text selection dragged out of the cards)',
      drag_rule is not None
      and 'cursor:grabbing' in drag_rule.group(2)
      and 'user-select:none' in drag_rule.group(2))

# ── 2. the drag-vs-tap decision lives in JS, and cannot leak ─────────────
i = JS.index('function enableDragScroll(')
drag_fn = JS[i:JS.index('\n}', i) + 2]
drag_fn_nc = re.sub(r'(?m)^\s*//.*$', '', re.sub(r'/\*.*?\*/', '', drag_fn, flags=re.DOTALL))

check('a real drag still suppresses the click it ends with, so panning never '
      'also opens a token',
      'swallowClick = moved' in drag_fn_nc)

check('...via one capture-phase listener bound once, not a listener added on '
      'each release (which is left behind when a drag ends off the rail and '
      'fires no click, and then eats the next genuine tap)',
      drag_fn_nc.count("addEventListener('click'") == 1
      and re.search(r"addEventListener\('click'.*?\}\s*,\s*true\s*\)", drag_fn_nc, re.DOTALL))

check('mousedown clears the flag, so a stale suppression can never outlive '
      'the gesture that set it',
      re.search(r"addEventListener\('mousedown'.*?swallowClick\s*=\s*false", drag_fn_nc, re.DOTALL))

check('the flag is consumed when it fires, so it suppresses one click and '
      'not every click after it',
      re.search(r'if\s*\(\s*!\s*swallowClick\s*\)\s*return;\s*swallowClick\s*=\s*false', drag_fn_nc))

# ── 3. the handler the cards depend on is still wired ───────────────────
check('surge cards still carry data-action="open-surge" for the delegated '
      'click handler to find',
      'data-action="open-surge"' in JS)
check('...and that handler routes the token into the Live Market feed',
      re.search(r'open-surge.*?prependSearchedToken\(', JS, re.DOTALL) is not None)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
