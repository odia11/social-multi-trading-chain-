"""The buy panels: what the user sees before they press Confirm.

Both surfaces with a Buy button -- Live Market's inline panel and the token
detail card -- since a ceiling shown on one and not the other is a ceiling
the user cannot rely on.

The backend now holds a spend ceiling. That is worth nothing if the screen
still says "Amount" and then reports "Bought for $100" when $97.43 of token
was bought -- the number on screen was the whole complaint.

So this checks the things a user would notice:

  the input asks what they will SPEND AT MOST, not an unqualified amount;
  the costs are itemised before anything is signed;
  the slippage reserve is named as held back, not charged, because it is;
  a price that expires says so instead of being executed at a new number;
  and the confirmation says what was BOUGHT, not what was entered.

Parsed rather than eyeballed: this file is checked with a JS parser and the
behaviour is asserted against the source, since there is no browser here.
"""
import json
import os
import re
import subprocess
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
JS = open(REPO + '/static/live-market-pro.js').read()
HTML = open(REPO + '/templates/live_market_pro.html').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    """One function's body, from its declaration to the next top-level one."""
    m = re.search(r'^function ' + name + r'\(.*?^\}', JS, re.S | re.M)
    assert m, f'no function {name}'
    return m.group(0)


# ── the file still parses ──
node = subprocess.run(['node', '--check', REPO + '/static/live-market-pro.js'],
                      capture_output=True, text=True)
check('live-market-pro.js parses', node.returncode == 0)

# ── the amount is presented as a ceiling ──
# The buy screen is the full sheet now (see tests/test_buy_sheet.py); the
# in-card panel openBuyPanel used to build is gone. What that panel had to
# SAY has not changed at all, so these checks follow the wording to where it
# now lives rather than being dropped with the markup that carried it.
panel = fn('openBuySheet') + HTML
check('the EVM input asks what the user will spend AT MOST, not an unqualified '
      '"Amount" — on these chains that number is the ceiling and the purchase '
      'is what remains', 'You spend at most' in panel)
check('...and Solana, which has no ceiling to price against, is not given the '
      'same wording', "'You spend'" in panel)
check('the currency is still named next to the amount', 'pt-buy-cur' in panel)
check('a breakdown area is rendered with it', 'pt-quote-' in panel)
# The keypad re-prices instead of an input's "input" event, since there is
# no text field to type into any more.
check('entering an amount re-prices, so the breakdown follows the amount',
      'scheduleQuote(_sheetIdx)' in JS)
check('...on the EVM chains only — Solana would have nothing truthful to show '
      'there', 'EVM_TRADE_CHAINS[t.chain]) scheduleQuote' in JS)

# ── pricing ──
sched = fn('scheduleQuote')
check('pricing is debounced rather than fired per keystroke, which would spend '
      'the rate limit on numbers the user is still typing',
      'clearTimeout' in sched and 'setTimeout' in sched and '450' in sched)
check('a previous quote is dropped the moment the amount changes, so a stale '
      'price can never be the one executed', 'delete _quotes[idx]' in sched)
check('the user is told pricing is happening', 'Pricing…' in sched)

fq = fn('fetchQuote')
check('the panel prices through /api/trade/quote — the same quote the buy then '
      'executes, so the screen and the trade cannot disagree',
      "'/api/trade/quote'" in fq)
check('it sends the amount as the SPEND CEILING', 'max_spend_usd' in fq)
check('a late answer for an amount the user has since changed is discarded',
      'parseFloat(input.value) !== amt' in fq)
check('a quote that cannot execute shows the real reason instead of a price',
      'reject_reason' in fq and 'can_execute === false' in fq)
check('...and clears any stored quote, so Confirm cannot fall back to it',
      '_quotes[idx] = null' in fq)

# ── what is shown ──
rq = fn('renderQuote')
check('every cost is itemised', 'costs_by_kind' in rq)
check('...under names a person recognises rather than the engine\'s own keys',
      'COST_LABELS' in rq)
for kind, label in (('source_gas', 'Network fee'), ('platform_fee', 'OrcAgent fee'),
                    ('slippage_reserve', 'Slippage reserve')):
    check(f'{kind} reads as "{label}"', f"'{label}'" in JS)
check('what is spent is shown at the top', 'You spend' in rq)
check('...and what is actually bought at the bottom, which is the number the '
      'old panel never showed at all', 'You get' in rq and 'token_purchase_usd' in rq)
check('the slippage reserve is explained as HELD BACK rather than charged, '
      'because that is what it is — anything unused stays the user\'s',
      'held back against' in rq and 'stays yours' in rq)

tick = fn('tickQuoteExpiry')
check('the price carries a visible countdown, since the backend really does '
      'expire it', "'Price held for '" in tick)
check('an expired price says so and is discarded rather than quietly executed',
      'expired' in tick and '_quotes[idx] = null' in tick)

# ── confirming ──
cb = fn('confirmBuy')
check('Confirm executes the QUOTE the user was shown, not a fresh pricing a '
      'moment later', "'/api/trade/execute'" in cb and 'quote_id: q.id' in cb)
check('...only while that quote is for this exact amount and has not expired',
      'q.amt === amt' in cb and 'q.expiresAt > Date.now()' in cb)
check('without a live quote it still uses the ordinary buy route, which prices '
      'server-side anyway — so this is about honouring what was on screen, not '
      'about the total being right',
      "'/api/evm/trade/buy'" in cb and "'/api/bsc/trade/buy'" in cb)
check('a quote that expired between being shown and being confirmed re-prices '
      'instead of executing at a number the user never saw',
      'd.requote' in cb and 'scheduleQuote(idx)' in cb)
check('the button says what is happening while it happens', "'Buying…'" in cb)

check('the confirmation reports what was BOUGHT. "Bought for $100" when $97.43 '
      'of token was bought is the exact mismatch this change removes',
      'd.amount_usdc' in cb and "'Bought '" in cb)
check('...and names the amount spent alongside it, so the difference is visible '
      'rather than hidden', 'max_spend_usd' in cb and '(spent ' in cb)
check('a completed buy clears its quote so the next one is priced fresh',
      'delete _quotes[idx]' in cb)

# ── it is drawn ──
for cls in ('pt-quote', 'pt-quote-row', 'pt-quote-get', 'pt-quote-note',
            'pt-quote-bad', 'pt-quote-stale', 'pt-buy-label'):
    check(f'.{cls} is styled', '.' + cls + '{' in HTML)
check('the figures line up in columns, which is the whole point of a breakdown',
      'tabular-nums' in HTML)
check('...and use the page\'s own tokens rather than hardcoded colours, so the '
      'panel matches the surface it sits on',
      re.search(r'\.pt-quote\{[^}]*var\(--', HTML) is not None)

# ── nothing invented ──
check('no cost is displayed that the backend did not send: the rows are built '
      'by iterating the response, not from a hardcoded list',
      'for(var k in kinds)' in rq)


# ── the token card: the other surface with a Buy button ───────────────────
TC  = open(REPO + '/static/token-card.js').read()
TCC = open(REPO + '/static/token-card.css').read()

node2 = subprocess.run(['node', '--check', REPO + '/static/token-card.js'],
                       capture_output=True, text=True)
check('token-card.js parses', node2.returncode == 0)


def tcfn(name):
    m = re.search(r'^(?:async )?function ' + name + r'\(.*?^\}', TC, re.S | re.M)
    assert m, f'no function {name}'
    return m.group(0)


exec_fn = tcfn('executeTrade')
check('the card\'s Buy button passes the CHAIN to the trade. Without it the chain '
      'defaulted to solana, so every EVM token bought from this card went to the '
      'Solana route and was rejected as an invalid mint — the EVM branches were '
      'unreachable from this button entirely',
      'chain)' in exec_fn and 'tokenAddress, chain)' in exec_fn)
check('...and the panel supplies it from the pair being viewed',
      '_lmtdPair && _lmtdPair.chainId' in TC)

do = tcfn('_doTrade')
check('Base, Arbitrum and Polygon route to the EVM buy, not to Solana',
      '_TC_EVM_CHAINS.indexOf(chain)' in do and "'/api/evm/trade/buy'" in do)
check('...sending the chain with the amount', "chain: chain" in do)

side = tcfn('_lmtdSidePanelHtml')
check('the input\'s unit follows the chain. It was hardcoded to SOL, so on BSC '
      'the field said SOL while the amount was spent as USDC',
      '_tcUnit(chain)' in side and "'SOL'" not in side.split('lmtd-sol-input-unit')[1][:80])
check('an EVM buy is labelled as a spend ceiling here too',
      'You spend at most' in side)
check('the percentage chips are dropped on EVM chains, because they work off the '
      'SOL balance and would be percentages of the wrong currency entirely',
      'isEvm ? \'\'' in side)
check('a breakdown area is rendered', 'lmtd-quote' in side)
check('typing re-prices', 'oninput="_lmtdQuote()"' in side)

q = tcfn('_lmtdQuote')
check('the card prices through the SAME endpoint as Live Market, so the two '
      'surfaces cannot show different numbers for one trade',
      "'/api/trade/quote'" in TC)
check('...only for an EVM buy — a Solana buy has no ceiling to price against',
      '_tcIsEvm(chain)' in q and "_lmtdSide !== 'buy'" in q)
check('pricing is debounced here too', 'clearTimeout' in q and '450' in q)
check('the breakdown is priced when the panel opens, not only after a keystroke: '
      'the field carries a default amount, and a breakdown that appeared only on '
      'typing would leave that default unexplained',
      '_lmtdQuote();' in tcfn('_lmtdWireSidePanel'))

fq2 = tcfn('_lmtdFetchQuote')
check('a late answer for a changed amount is discarded',
      "parseFloat(input.value) !== amt" in fq2)
check('the costs are itemised from the response', 'costs_by_kind' in fq2)
check('...and the reserve is explained as held back rather than charged',
      'held back against' in fq2 and 'stays yours' in fq2)
check('a quote that cannot execute shows the reason, not a price',
      'reject_reason' in fq2)

for cls in ('lmtd-quote', 'lmtd-quote-row', 'lmtd-quote-get', 'lmtd-quote-note',
            'lmtd-quote-bad', 'lmtd-spend-label'):
    check(f'.{cls} is styled', '.' + cls + '{' in TCC)
check('the card\'s figures line up in columns too', 'tabular-nums' in TCC)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
