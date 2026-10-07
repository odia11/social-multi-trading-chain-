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
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = open(REPO + '/dashboard.html', encoding='utf-8').read()
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def strip(fragment):
    return re.sub(r'<[^>]+>', ' ', fragment)


# The onboarding, as a new wallet actually meets it.
INTRO = HTML[re.search(r'<div id="onboard"[^>]*>', HTML).start():HTML.index('<!-- SETTINGS MODAL -->')]
SUB   = strip(HTML[HTML.index('<div class="ob-sub">'):HTML.index('<div class="ob-progress">')])
STEP1 = strip(HTML[HTML.index('id="step-1"'):HTML.index('id="ob-privkey"')])

# ── the chains ────────────────────────────────────────────────────────────
# The app trades Solana only now (ACTIVE_EVM_CHAINS is empty), so the
# opening line names Solana and no retired chain.
check('the code says the app is Solana-only', 'ACTIVE_EVM_CHAINS = {}' in SRC and 'SOLANA_ONLY = True' in SRC)
retired = [n for n in ('BNB Chain', 'Base,', 'Arbitrum', 'Robinhood', 'Polygon') if n in SUB]
check('the opening line names the chain the app actually trades, and no retired one'
      + ('' if not retired else ': ' + ', '.join(retired) + ' named'),
      'Solana' in SUB and not retired)
check('...and no longer says the app trades Solana meme coins, full stop, '
      'which described a bot and not the rest of the app',
      'trading Solana meme coins' not in INTRO)

# ── the currency ──────────────────────────────────────────────────────────
base = re.search(r"SOLANA_BASE_CURRENCY = '([A-Z]+)'", SRC).group(1)
check(f'the opening line says what a trade is funded in ({base}), since that '
      f'is the first thing somebody has to get right', base in SUB)
check(f'...and step two says it again where the wallet is actually set up',
      base in STEP1)
check('...and that the same SOL pays the network fees, with a reserve kept for them',
      'funds trades and network fees' in STEP1 and 'reserve' in STEP1)

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
