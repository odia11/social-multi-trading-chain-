"""The Live Market feed's own chart should load and read like the app's other
one (the token-detail modal's LightweightCharts view), not visibly behind it.

WHAT WAS DIFFERENT
The modal opens on one token at a time, so its chart-data fetch just fires.
The feed can have several cards mounting within moments of each other (a fast
scroll, or several fitting in the first screen at once), and their real
candle-history fetches share one deliberately-paced queue -- GeckoTerminal,
not this app, rate-limits concurrent history requests for different pools, so
that pacing has to stay (see drainChartFetchQueue()'s own comment). But the
queue was plain FIFO: a card merely pre-warmed 250px before it was on screen
could sit ahead of one the user is looking at right now, and until its turn
came the chart showed nothing but a single flat placeholder candle with no
indication anything was even happening.

THE FIX
Two independent things, neither of which touches how OFTEN a request goes
out (the actual rate-limit-sensitive part):
  - a card known to be genuinely on screen right now (not just inside the
    prefetch margin) jumps ahead of merely-prewarmed ones in that same queue
  - the placeholder candle shows a loading shimmer until the first real
    answer lands, so a queued card reads as "loading" rather than "broken"
"""
import re
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()
CSS = open(REPO + '/static/live-market-redesign.css', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    i = JS.index('function ' + name + '(')
    depth = 0
    j = JS.index('{', i)
    start = j
    while True:
        if JS[j] == '{': depth += 1
        elif JS[j] == '}':
            depth -= 1
            if depth == 0: break
        j += 1
    return JS[i:j+1]


# ── the priority queue ──────────────────────────────────────────────────────
fetch_chart = fn('fetchChart')
check('a genuinely on-screen card can jump ahead of merely pre-warmed ones '
      'in the shared history-fetch queue',
      'priority' in fetch_chart and 'splice(' in fetch_chart)
drain_fn = fn('drainChartFetchQueue')
check("...without changing how MANY requests go out or how fast -- the "
      "pacing itself exists for a real upstream rate limit (GeckoTerminal, "
      "not this app) and is not this fix's to touch",
      '2100' in drain_fn)

observer = JS[JS.index('_cardObserver = new IntersectionObserver('):
               JS.index('rootMargin:')]
check('visibility is read from the real, unexpanded viewport rect -- '
      'IntersectionObserver.isIntersecting alone would be true for a card '
      'merely inside the 250px prefetch margin, not actually on screen',
      'boundingClientRect' in observer and 'st.visible' in observer)

chart_tick = fn('chartTick')
check('chartTick passes that visibility through to the fetch it makes',
      re.search(r'fetchChart\([^)]*st\.visible\)', chart_tick) is not None)

# ── the loading shimmer ─────────────────────────────────────────────────────
prime_chart = fn('primeChart')
check('a freshly-mounted card shows a loading state on its placeholder '
      'candle, rather than looking like a broken chart until its turn in '
      'the queue comes',
      'pt-chart-loading-shimmer' in prime_chart and 'classList.add' in prime_chart)
check('...cleared the moment chartTick gets ANY answer, real candle history '
      "or not -- its job is only to mark \"not the real chart yet\", not to "
      'track which kind of answer eventually arrived',
      'pt-chart-loading-shimmer' in chart_tick and 'classList.remove' in chart_tick)

check('the shimmer keyframe animation exists in the stylesheet actually '
      'loaded for this page', '@keyframes pt-chart-shimmer' in CSS)
check('...and the empty state ("Not enough data yet") is an actual styled '
      'element now, not a bare unstyled <div>', '.pt-chart-empty{' in CSS)

# ── crispness ────────────────────────────────────────────────────────────
check('horizontal gridlines are pixel-snapped to a half-pixel, so a 1px '
      'stroke renders crisp instead of blurred across two rows',
      'Math.round(yy)+0.5' in JS or 'Math.round(yy) + 0.5' in JS)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
