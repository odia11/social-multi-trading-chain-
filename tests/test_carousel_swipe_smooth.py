"""Live Market's horizontal rails (Surging Now, the story rail, the trader
rail) must swipe/scroll smoothly on both touch and desktop.

WHAT WAS HAPPENING
Two separate bugs, both on templates/live_market_pro.html and
static/live-market-pro.js -- the single template served for /live-market on
every viewport (mobile and desktop alike; live_market.html is the old,
unrouted mobile-only template kept on disk but not served):

1. Desktop had no way to scroll these rails at all. They are plain
   overflow-x:auto strips with the native scrollbar hidden (scrollbar-width:
   none plus a ::-webkit-scrollbar{display:none} rule, for the mobile look),
   and nothing bound a mouse drag gesture -- a desktop visitor with no
   touchscreen and no trackpad horizontal-scroll habit just saw a strip cut
   off mid-card with no way to reach the rest.

2. On mobile, loadSurges() rebuilt #pt-surge-rail's innerHTML from scratch
   every 12 seconds (setInterval(loadSurges, 12000)), unconditionally. A
   full innerHTML replace resets scrollLeft to 0 and cancels the browser's
   own momentum/inertia scrolling outright -- if that tick landed while a
   finger was still moving on the strip (a real chance, given how short the
   rail is and how often it refreshes), the swipe would visibly stutter or
   snap back. This is exactly what "swiping isn't smooth" looks like from
   the user's thumb.

THE FIX
- enableDragScroll(el) in live-market-pro.js binds mousedown/mousemove/
  mouseup to give #pt-story-rail, #pt-surge-rail and #pt-trader-rail plain
  click-and-drag panning on desktop, and swallows the click a real drag
  would otherwise fire on release (so panning never also opens a token).
  Wired up once in the DOMContentLoaded handler.
- loadSurges() now captures rail.scrollLeft before replacing innerHTML and
  restores it after, and skips the rebuild entirely for a tick where
  _railsBeingTouched['pt-surge-rail'] is true (set/cleared by touchstart/
  touchend/touchcancel listeners enableDragScroll also binds) -- the next
  12s tick picks up the fresh data once the finger actually lifts.
- CSS on all three rails: -webkit-overflow-scrolling:touch (old iOS Safari
  momentum), overscroll-behavior-x:contain (a rail's own scroll no longer
  chains into the page behind it), and cursor:grab / .pt-rail-dragging
  {cursor:grabbing} to make the new desktop drag affordance visible.

Checked against the actual source (not just presence of keywords), so a
future edit that silently drops the scroll-preservation, the touch guard,
or the drag binding fails this test rather than shipping unnoticed.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()
HTML = open(REPO + '/templates/live_market_pro.html', encoding='utf-8').read()

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# ── 1. desktop drag-scroll exists and is wired to all three rails ─────────
check('enableDragScroll() is defined',
      re.search(r'function\s+enableDragScroll\s*\(', JS) is not None)

drag_fn_m = re.search(r'function\s+enableDragScroll\s*\([^)]*\)\s*\{(.*?)\n\}',
                       JS, re.DOTALL)
drag_fn = drag_fn_m.group(1) if drag_fn_m else ''

check('enableDragScroll binds mousedown, mousemove and mouseup so a mouse '
      'drag actually pans the rail',
      "addEventListener('mousedown'" in drag_fn
      and "addEventListener('mousemove'" in drag_fn
      and "addEventListener('mouseup'" in drag_fn)

check('...and it updates el.scrollLeft from the drag delta, rather than '
      'just tracking state without moving anything',
      'el.scrollLeft' in drag_fn)

check('a genuine drag suppresses the click it would otherwise fire on '
      'release, so panning never also opens whatever card is under the '
      'cursor when the mouse comes up',
      'preventDefault' in drag_fn and 'moved' in drag_fn)

check('enableDragScroll also tracks touch start/end so callers can tell '
      'whether a rail is mid-gesture',
      "addEventListener('touchstart'" in drag_fn
      and ("addEventListener('touchend'" in drag_fn
           or "addEventListener('touchcancel'" in drag_fn))

for rail_id in ('pt-story-rail', 'pt-surge-rail', 'pt-trader-rail'):
    check(f'enableDragScroll is actually called on #{rail_id}',
          re.search(r"enableDragScroll\(\s*document\.getElementById\(['\"]"
                     + re.escape(rail_id) + r"['\"]\)\s*\)", JS) is not None)

# ── 2. loadSurges() no longer destroys an in-progress swipe ───────────────
surges_fn_m = re.search(r'function\s+loadSurges\s*\(\s*\)\s*\{(.*?)\n\}', JS, re.DOTALL)
assert surges_fn_m, 'loadSurges() not found'
surges_fn = surges_fn_m.group(1)

check('loadSurges() bails out for a tick while pt-surge-rail is mid-touch, '
      'instead of rebuilding out from under an active gesture',
      "_railsBeingTouched['pt-surge-rail']" in surges_fn
      or '_railsBeingTouched["pt-surge-rail"]' in surges_fn)

check('loadSurges() captures scrollLeft before replacing innerHTML',
      re.search(r'\bvar\s+\w+\s*=\s*rail\.scrollLeft', surges_fn) is not None)

check('...and restores scrollLeft after replacing innerHTML, so a periodic '
      'refresh no longer snaps the strip back to the start',
      re.search(r'rail\.scrollLeft\s*=\s*\w+', surges_fn) is not None)

# order matters: the innerHTML write must sit between the capture and the
# restore, not before the capture or after the restore.
capture_idx = surges_fn.index('rail.scrollLeft')
innerhtml_idx = surges_fn.index('rail.innerHTML =')
restore_idx = surges_fn.rindex('rail.scrollLeft')
check('the capture happens before the rebuild, and the restore happens '
      'after it (not the other way around)',
      capture_idx < innerhtml_idx < restore_idx)

# ── 3. CSS: touch momentum, scroll containment, and a visible drag cursor ─
for rail_class in ('.pt-story-rail', '.pt-surge-rail', '.pt-trader-rail'):
    rule_m = re.search(re.escape(rail_class) + r'\{([^}]*)\}', HTML)
    assert rule_m, f'{rail_class} base rule not found'
    rule = rule_m.group(1)
    check(f'{rail_class} keeps -webkit-overflow-scrolling:touch for old '
          'iOS Safari momentum scrolling',
          '-webkit-overflow-scrolling:touch' in rule)
    check(f'{rail_class} contains its own horizontal overscroll so it does '
          "not chain into the page's scroll behind it",
          'overscroll-behavior-x:contain' in rule)
    check(f'{rail_class} shows a grab cursor, the desktop drag affordance',
          'cursor:grab' in rule)

check('a .pt-rail-dragging rule shows a grabbing cursor while a drag is '
      'actually in progress (toggled by enableDragScroll)',
      re.search(r'\.pt-rail-dragging[^{]*\{[^}]*cursor:grabbing', HTML) is not None)

check('enableDragScroll toggles the pt-rail-dragging class on mousedown',
      "classList.add('pt-rail-dragging')" in drag_fn)
check('...and removes it again on mouseup',
      "classList.remove('pt-rail-dragging')" in drag_fn)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
