"""The magnifier in the open mobile search sits in the middle of the field.

It was placed with its TOP edge on the field's middle (top:24px /
transform:none), so it hung ~7px below the placeholder text on every page.
Both rules that place it now pull it up by half its own height.
"""
import os, re
ROOT = os.path.join(os.path.dirname(__file__), '..')
NAV = open(os.path.join(ROOT, 'static', 'navbar.css')).read()
HOME = open(os.path.join(ROOT, 'static', 'home-mobile.css')).read()

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

def rule(css, sel):
    m = re.search(re.escape(sel) + r'\{([^}]*)\}', css)
    return m.group(1) if m else ''

portal = rule(NAV, '#pt-nb-search-portal .pt-nb-search-icon')
check('open search (all pages): icon centred on the 48px field',
      'top:24px' in portal and 'transform:translateY(-50%)' in portal and 'transform:none' not in portal)
check('...and no inline-SVG line box pushing it down', 'line-height:0' in portal and 'display:flex' in portal)
home = rule(HOME, 'body.oa-home-mobile .pt-nb-search-wrap.mobile-search-open .pt-nb-search-icon')
check('open search (home): icon centred too',
      'transform:translateY(-50%)' in home and 'transform:none' not in home)
check('the placeholder leaves room after the icon', 'padding:0 16px 0 46px' in rule(NAV, '#pt-nb-search-portal .pt-nb-search'))
nav_js = open(os.path.join(ROOT, 'static', 'navbar.js')).read()
check('phones fetch the new home-mobile.css (version bumped)', "home-mobile.css?v=10" in nav_js)
raise SystemExit(0 if all(checks) else 1)
