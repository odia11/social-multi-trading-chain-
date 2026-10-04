"""The Info page has to describe the app that exists.

It described the one from before the multi-chain work: "a social trading
platform for Solana meme coins", "deposit SOL to fund trading", a fee
"calculated on the SOL amount", and network fees as "standard Solana network
fees". Every one of those was true once. None of them was true any more, and
this is the page a user reads to find out what they are paying.

Prose goes stale silently — there is no error, no failing request, nothing to
notice. So where a claim on the page has a matching fact in the code, this
checks them against each other rather than against a string I typed here: the
chain list comes from SURGE_ALERT_CHAIN_NAMES, and the funding currency from
SOLANA_BASE_CURRENCY. Change the code and the page has to follow.
"""
import os
import re
import sys
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INFO = open(REPO + '/templates/info.html').read()
SRC = open(REPO + '/dashboard.py').read()
CSS = open(REPO + '/static/navbar.css').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# ── About follows the product that is actually active ──────────────────────
about = INFO[INFO.index('<section class="info-section" id="about">'):
             INFO.index('<!-- ═══════════ DOCS ═══════════ -->')]
check('the active product is explicitly Solana-only in code',
      'SOLANA_ONLY = True' in SRC and 'ACTIVE_EVM_CHAINS = {}' in SRC)
check('About describes OrcAgent as a Solana social trading platform',
      'Solana social trading platform' in about)
check('About no longer contains the old duplicated or multichain copy',
      'Solana, Solana' not in about.replace('\n      ', ' ')
      and 'every supported chain' not in about
      and 'whichever chain' not in about)
check('the refreshed About hero carries the current product line',
      'Trade it. Share it.' in about and 'Built on Solana' in about)
for feature in ('Live Market', 'Auto Trading', 'Social &amp; Copy Trading',
                'Launch Tokens', 'Messages', 'One Portfolio'):
    check(f'About includes {feature}', feature in about)

# ── the funding currency ──────────────────────────────────────────────────
base = re.search(r"SOLANA_BASE_CURRENCY = '([A-Z]+)'", SRC).group(1)
check(f'the page tells you to fund the trading wallet in {base}',
      f'<strong>{base}</strong> to fund trading' in INFO)
check('the docs explain that SOL is still needed for Solana network costs',
      'SOL reserve available' in INFO)
check('the page no longer advertises an active cross-chain bridge',
      'there is no active cross-chain bridge in the product'
      in INFO.replace('\n      ', ' '))

# ── the fee, which is the reason anyone reads this page ───────────────────
flat = INFO.replace('\n      ', ' ').replace('\n', ' ')
check('the fee is no longer described as a percentage of a SOL amount',
      'on the SOL amount' not in flat)
check('the page states the thing the pricing rewrite actually changed: the '
      'amount you enter is the most that leaves your wallet',
      'the most that leaves your wallet' in flat)
check('...and that the fee, network fee and slippage reserve come OUT of it '
      'rather than being added to it',
      'come out of it' in flat and 'what remains is what buys the token' in flat)

# ── network scope ─────────────────────────────────────────────────────────
check('fees describe Solana/Jupiter costs instead of inactive EVM chains',
      'Every trade runs on Solana' in flat
      and 'OrcAgent supports Solana only' in flat)
check('the docs distinguish USDC trading balance from SOL network costs',
      'SOL is the trading balance OrcAgent uses for Solana buys and sells' in flat
      and 'small amount of SOL for network fees' in flat)

# ── it must still be well-formed ──────────────────────────────────────────
VOID = {'img','br','hr','input','meta','link','source','area','base','col'}
class P(HTMLParser):
    def __init__(self): super().__init__(); self.st=[]; self.bad=[]
    def handle_starttag(self, t, a):
        if t not in VOID: self.st.append(t)
    def handle_endtag(self, t):
        if self.st and self.st[-1] == t: self.st.pop()
        elif t in self.st:
            while self.st and self.st.pop() != t: pass
        else: self.bad.append(t)
p = P(); p.feed(INFO)
check(f'the page is still well-formed{"" if not p.st else ": unclosed " + ", ".join(p.st)}',
      not p.st and not p.bad)

# ── the menu row the icons broke ──────────────────────────────────────────
def gap(rule):
    m = re.search(re.escape(rule) + r'\{([^}]*)\}', re.sub(r'/\*.*?\*/', '', CSS, flags=re.S))
    if not m: return None
    v = re.search(r'(?:^|;)gap:\s*([0-9.]+)px', m.group(1))
    return float(v.group(1)) if v else None

check('menu rows leave room between the icon and the label — 6px was set when '
      'they were text only, and beside a 16px glyph it reads as none',
      gap('.pt-nb-more-item') and gap('.pt-nb-more-item') >= 9)
check('...in the mobile menu too, where the rule is restated rather than '
      'inherited', gap('.pt-nb-nav .pt-nb-more-item') == gap('.pt-nb-more-item'))
check('...and that override now states its own layout instead of silently '
      'leaning on the base rule for it',
      'display:flex' in re.search(r'\.pt-nb-nav \.pt-nb-more-item\{([^}]*)\}', CSS).group(1))
check('the label truncates, not the row — clipping the flex container cut the '
      'icon off instead',
      'text-overflow:ellipsis' not in
      re.search(r'\.pt-nb-nav \.pt-nb-more-item\{([^}]*)\}', CSS).group(1)
      and '.pt-nb-more-item > span{overflow:hidden' in CSS)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
