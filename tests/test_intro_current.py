"""The first screen has to describe the app that exists.

It said: "Connect your wallet to start trading Solana meme coins
automatically." That was true when the app was a Solana auto-trading bot. It
is now six chains, funded in USDC, with manual trading, a social feed and
copy-trading -- so the very first sentence a new person read was wrong about
the chains, wrong about the currency, and described maybe a third of the app.

Step two was no better: "Enable Bot Trading ... so the bot can execute
trades". That key is also what buys in Live Market and what copy-trading
uses. Someone who did not want a bot had no reason to think it applied to
them.

Prose goes stale silently -- no error, no failing request, nothing to notice.
So where a claim has a matching fact in the code, this checks them against
each other rather than against a string typed here: the chain list comes from
SURGE_ALERT_CHAIN_NAMES, the funding currency from SOLANA_BASE_CURRENCY.
Change the code and the intro has to follow.
"""
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
HTML = open(REPO + '/dashboard.html', encoding='utf-8').read()
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def strip(fragment):
    return re.sub(r'<[^>]+>', ' ', fragment)


# The onboarding, as a new wallet actually meets it.
INTRO = HTML[HTML.index('<div id="onboard">'):HTML.index('<!-- SETTINGS MODAL -->')]
SUB   = strip(HTML[HTML.index('<div class="ob-sub">'):HTML.index('<div class="ob-progress">')])
STEP1 = strip(HTML[HTML.index('id="step-1"'):HTML.index('id="ob-privkey"')])

# ── the chains ────────────────────────────────────────────────────────────
chains = re.search(r'SURGE_ALERT_CHAIN_NAMES = \{(.*?)\}', SRC, re.S).group(1)
names = re.findall(r":\s*'([^']+)'", chains)
missing = [n for n in names if n.split()[0] not in SUB]
check('the opening line names the chains the app actually trades'
      + ('' if not missing else ': ' + ', '.join(missing) + ' missing'),
      not missing)
check('...and no longer says the app trades Solana meme coins, full stop, '
      'which is what it said while five other chains were live',
      'trading Solana meme coins' not in INTRO)

# ── the currency ──────────────────────────────────────────────────────────
base = re.search(r"SOLANA_BASE_CURRENCY = '([A-Z]+)'", SRC).group(1)
check(f'the opening line says what a trade is funded in ({base}), since that '
      f'is the first thing somebody has to get right', base in SUB)
check(f'...and step two says it again where the wallet is actually set up',
      base in STEP1)
check('...without telling anyone to hold a gas token, which the app arranges',
      'network fees are handled' in STEP1.lower())

# ── what the trading key is for ───────────────────────────────────────────
check('the trading key is not described as a bot-only thing — it is what buys '
      'in Live Market and what copy-trading spends too, so somebody who wants '
      'neither a bot nor nothing still needs to understand it',
      'Enable Bot Trading' not in INTRO
      and 'copy-trading' in STEP1 and 'Live Market' in STEP1)
check('...and it still says plainly that this must not be a main wallet',
      'main wallet' in INTRO)
check('...and that the key is encrypted and never shown back',
      'double-encrypted' in STEP1 and 'logs' in STEP1)

# ── skipping ──────────────────────────────────────────────────────────────
check('skipping says what still works without a key, rather than reading as '
      'an abandoned setup',
      'browse the market' in INTRO.lower() and 'buy or sell' in INTRO.lower())

# ── the social half of the app exists at all ──────────────────────────────
check('the opening line mentions following and copying other traders, which '
      'is half of what this app is and was not mentioned at all',
      'copy' in SUB.lower() and 'traders' in SUB.lower())

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
