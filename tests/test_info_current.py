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
import re
import sys
from html.parser import HTMLParser

REPO = '/home/user/Orc-agent-Solana-chain-'
INFO = open(REPO + '/templates/info.html').read()
SRC = open(REPO + '/dashboard.py').read()
CSS = open(REPO + '/static/navbar.css').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# ── the page must name the chains the app actually trades ─────────────────
chains = re.search(r'SURGE_ALERT_CHAIN_NAMES = \{(.*?)\}', SRC, re.S).group(1)
names = re.findall(r":\s*'([^']+)'", chains)
missing = [n for n in names if n not in INFO]
check(f'every chain the app trades is named on the page'
      f'{"" if not missing else ": " + ", ".join(missing) + " missing"}', not missing)
check('...and it no longer calls itself Solana-only, which it was when the page '
      'was written', 'platform for Solana meme coins' not in INFO)

# ── the funding currency ──────────────────────────────────────────────────
base = re.search(r"SOLANA_BASE_CURRENCY = '([A-Z]+)'", SRC).group(1)
check(f'the page tells you to fund the wallet in {base}, which is what the code '
      f'settled on', f'Deposit\n      <strong>{base}</strong>' in INFO
      or f'<strong>{base}</strong> to fund trading' in INFO)
check('...and no longer says to deposit SOL for that, which stopped being true '
      'when one currency was chosen',
      'Deposit\n      SOL to its address to fund trading' not in INFO
      and 'SOL to its address to fund trading' not in INFO)
check('...while still explaining that Solana needs a little SOL of its own for '
      'network fees, because that part did not change',
      'SOL for its own' in INFO.replace('\n      ', ' '))
check('...and that a chain without your balance on it is bridged for you, since '
      'that is what makes one currency work at all',
      'bridge it there' in INFO.replace('\n      ', ' '))

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

# ── network fees, and who provides the gas ────────────────────────────────
check('network fees are described per chain rather than as Solana\'s',
      'standard Solana network and' not in flat and 'the chain it happens on' in flat)
check('...and the page says you never need to hold a chain\'s gas token',
      'never have to hold' in flat)
check('...while being explicit that the gas is still CHARGED to you — calling '
      'it free would be the one dishonest sentence on the page',
      'charged to you, not subsidised' in flat)

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
