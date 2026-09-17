"""The quick-percent buy chips must fill in a USDC amount, not a SOL one.

WHAT WAS HAPPENING
Every buy on the token-detail panel is denominated in USDC -- Solana
included, since the app-wide move off SOL-funded Solana buys (see
test_solana_usdc.py). But _lmtdSetPct(), which fills the amount field when
someone taps 25/50/75/100%, still computed that fraction of _lmtdSolBalance
-- the wallet's native SOL holdings, fetched from /api/wallet/balance.

The result: clicking 50% on a wallet holding 2 SOL filled the field with
"1". That value is sent to the server as amount_usdc and read as exactly
that -- a one-dollar buy, not "half of whatever 2 SOL happens to be worth"
(which at almost any real SOL price is nowhere near $1). The field's own
unit label correctly says USDC (see test_buy_panel_usd.py) while the number
inside it came from an entirely different asset's balance.

EVM chains were already spared this by a different route: their percentage
chips were simply dropped, specifically because the only balance on hand
was SOL and "the trade is denominated in USDC, so those percentages would
be of the wrong currency entirely" -- the exact same reasoning, just never
extended to Solana once Solana became USDC-funded too.

THE FIX
/api/wallet/usdc-summary already returns every chain's real USDC balance in
one call (solana_usdc, plus evm_chains). The panel now fetches it, records
which chain is currently active, and the percent chips read THAT balance --
restored on every chain, working correctly, rather than dropped anywhere.
"""
import re
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(REPO + '/static/token-card.js', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    i = JS.index('function ' + name + '(')
    depth = 0
    j = JS.index('{', i)
    while True:
        if JS[j] == '{': depth += 1
        elif JS[j] == '}':
            depth -= 1
            if depth == 0: break
        j += 1
    return JS[i:j+1]


set_pct = fn('_lmtdSetPct')
check('the percent chips read a real USDC balance, not the wallet\'s SOL '
      'holdings', '_lmtdUsdcBalances' in set_pct and '_lmtdSolBalance' not in set_pct)
check('...for the chain the panel is actually open on, not always Solana',
      '_lmtdActiveChain' in set_pct)

check('that balance is fetched from the same endpoint the Wallet page uses '
      'for its own USDC figures, so the two can never disagree',
      "fetch('/api/wallet/usdc-summary'" in JS)
check('...covering every chain the panel can open on: solana_usdc plus '
      'every EVM chain\'s own figure, not just one hardcoded chain',
      "solana_usdc" in JS and "d.evm_chains" in JS)

panel = fn('_lmtdSidePanelHtml')
check('the panel records which chain is active before the chips can be '
      'clicked, so _lmtdSetPct knows which balance is "this chain\'s"',
      '_lmtdActiveChain = chain' in panel)
check('percent chips are no longer unconditionally dropped for EVM chains -- '
      'that workaround is obsolete now that a real balance exists for them '
      'too', "isEvm ? ''" not in panel)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
