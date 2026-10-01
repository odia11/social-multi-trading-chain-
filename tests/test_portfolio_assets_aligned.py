"""Portfolio -> Assets: every row lines up.

USDC and SOL had no swap button and a slightly bigger coin and padding, so
their figures ended 38px further right than every token's, and the icons and
names stepped sideways from row to row (seen on a phone, 390px). All rows now
share one layout: the same padding, a 42px icon, one value-column width, and
an empty slot the width of the swap button on the two fixed rows.
Measured in a browser after the change: icon, name and value edge identical
on all rows at 390, 360 and 1280px.
"""
import os, re
ROOT = os.path.join(os.path.dirname(__file__), '..')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
css = open(os.path.join(ROOT, 'static', 'portfolio-redesign.css'), encoding='utf-8').read()
tail = css[css.index('/* Assets list: one layout for every row.'):]
def rule(sel):
    m = re.search(re.escape(sel) + r'\{([^}]*)\}', tail)
    return m.group(1) if m else ''
check('USDC/SOL rows and token rows share padding and gap',
      'padding:13px 4px' in rule('body.oa-portfolio .pf-asset-static,body.oa-portfolio .tok-row')
      and 'gap:12px' in rule('body.oa-portfolio .pf-asset-static,body.oa-portfolio .tok-row'))
check('...one icon size for every row',
      'width:42px;height:42px;flex:0 0 42px' in rule('body.oa-portfolio .pf-asset-coin,body.oa-portfolio .tok-logo,body.oa-portfolio .tok-init'))
check('...one value column, right-aligned',
      'min-width:84px;text-align:right' in rule('body.oa-portfolio .pf-asset-amount,body.oa-portfolio .tok-val'))
check('...and the fixed rows keep an empty slot exactly as wide as the swap button',
      'flex:0 0 var(--pf-act)' in rule('body.oa-portfolio .pf-asset-static::after')
      and 'width:var(--pf-act)' in rule('body.oa-portfolio .tok-trade-btn')
      and '--pf-act:32px' in rule('body.oa-portfolio'))
check('this block comes last, so the older mobile row rule cannot undo it',
      css.rindex('/* Assets list: one layout for every row.') > css.rindex('@media(max-width:600px)'))
raise SystemExit(0 if all(checks) else 1)
