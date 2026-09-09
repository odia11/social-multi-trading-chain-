"""A menu of sixteen identical text rows is read, not scanned.

Nothing in it said which destinations matter. Every entry was the same
weight, the same colour, the same shape — so finding Wallet took the same
effort as finding About, and Bot, which is the autonomous trading this
product is named for, sat between History and Live Trades looking exactly
like them: three plain rows, no way to tell that one of them is the thing
the platform does and the other two are records of it having done it.

Icons make a row recognisable before it is read. The accent on Bot is
deliberately quiet — enough to be found while scanning, not enough to
compete with the marker for where you actually are.

These checks RENDER the menu and parse what comes out, rather than matching
strings. A malformed icon is invisible in source and obvious in a browser,
which is the wrong way round.
"""
import ast
import re
import sys
import xml.etree.ElementTree as ET

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
CSS = open(REPO + '/static/navbar.css').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# Lift the menu out of the app and run it, so this tests the real output.
ns = {}
for nm in ('_NAV_ICONS', '_NAVBAR_PRIMARY', '_NAVBAR_MORE_LINKS'):
    node = next(n for n in ast.walk(TREE) if isinstance(n, ast.Assign)
                and any(getattr(t, 'id', '') == nm for t in n.targets))
    exec(ast.get_source_segment(SRC, node), ns)
for nm in ('_nav_icon', '_navbar_more_items_html'):
    node = next(n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == nm)
    exec(ast.get_source_segment(SRC, node), ns)

more = ns['_navbar_more_items_html']()
primary = ''.join(
    '<a href="%s" class="%s">%s<span>%s</span></a>'
    % (href, '', ns['_nav_icon'](key), label)
    for key, label, href in ns['_NAVBAR_PRIMARY'])

# ── every destination is recognisable ─────────────────────────────────────
anchors = re.findall(r'<a class="[^"]*"[^>]*>(.*?)</a>', more)
check('every destination in the menu carries an icon and a label',
      anchors and all('<svg' in a and '<span>' in a for a in anchors))
check('...the five primary links too, not only the secondary ones',
      primary.count('<svg') == len(ns['_NAVBAR_PRIMARY']))
check('...and Disconnect, which is the one row where hitting the wrong thing '
      'actually costs something', 'Disconnect Wallet' in more
      and more[more.index('Disconnect Wallet') - 400:].count('<svg') >= 1)

# ── the icons must survive a browser ──────────────────────────────────────
svgs = re.findall(r'<svg.*?</svg>', more + primary)
bad = []
for svg in svgs:
    try:
        ET.fromstring(svg)
    except ET.ParseError as e:
        bad.append(str(e))
check(f'every icon is well-formed XML — a broken path is invisible in source '
      f'and obvious on screen{"" if not bad else ": " + bad[0]}', not bad)
check('...and they all share one wrapper, so sixteen icons cannot drift into '
      'sixteen different sizes and stroke weights',
      len({re.match(r'<svg[^>]*>', s).group(0) for s in svgs}) == 1)
check('an unknown icon key renders nothing rather than a broken glyph — a '
      'missing icon should cost alignment, never a menu entry',
      ns['_nav_icon']('no-such-key') == '')

# ── what is marked as important ───────────────────────────────────────────
check('Bot is marked as a feature rather than another record page',
      'pt-nb-feature' in more)
check('...and it is the ONLY one so marked, because marking several is the '
      'same as marking none', more.count('pt-nb-feature') == 1)
check('...through a class, so it can be moved or removed without touching '
      'the menu itself', "'pt-nb-feature'" in SRC and '.pt-nb-feature' in CSS)
check('the accent lands on the icon, not the label — loud enough to find '
      'while scanning, quiet enough not to compete with where you are',
      '.pt-nb-feature .pt-nb-ic{' in CSS)

# ── the layout has to hold ────────────────────────────────────────────────
check('icons never shrink: a long label eats its own width, since a squashed '
      'glyph reads as a rendering fault', 'flex:0 0 16px' in CSS)
check('...and the label truncates rather than wrapping, so one row cannot '
      'become taller than its neighbours',
      '.pt-nb-more-item > span{overflow:hidden' in CSS)
check('the desktop pills stay sized to their content instead of stretching',
      '.pt-nb-nav a{display:inline-flex' in CSS)
check('...and drop their icons when the row is tight, rather than squeezing '
      'the tap targets that matter more',
      '.pt-nb-nav a .pt-nb-ic{display:none}' in CSS
      and '@media (min-width:1100px)' in CSS)
check('inside the mobile menu the icons always show, since there the entries '
      'are rows and there is room', "display:block;width:18px" in CSS)
check('the stylesheet still has balanced braces — one stray brace silently '
      'drops every rule after it', CSS.count('{') == CSS.count('}'))

# ── one source for both copies ────────────────────────────────────────────
check('the desktop popup and the mobile menu are still built from the same '
      'function, so their icons cannot disagree',
      SRC.count('_navbar_more_items_html(') >= 3)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
