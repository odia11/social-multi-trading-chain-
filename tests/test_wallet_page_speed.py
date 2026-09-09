"""The Wallet page shows a balance immediately.

WHY IT CRAWLED
One combined figure -- "AVAILABLE TO TRADE $3.02" -- is the sum of six real
balances on six different networks. They were read in a loop: Solana, then
bsc, then base, then arbitrum, then polygon, then robinhood. Six round trips,
one after the other, with the page showing nothing until the last one landed.
The wait was the SUM of them, so the slowest RPC of the six set the speed of
the whole page.

They have nothing to do with each other, so there was never a reason to make
them queue.

AND THE BRIDGE BUTTON
Gone from the action row. Buying on a chain that has no USDC already bridges
by itself -- it finds a chain with enough balance, moves the funds with a
buffer and finishes the purchase. Offering the same thing again as a manual
chore, in a row of four where the other three are things people actually do,
asked everyone to understand a piece of plumbing they never have to touch.
The endpoints stay: the automatic path is what uses them.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
WALLET = open(REPO + '/templates/wallet.html', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

summary = fn('api_wallet_usdc_summary')
code = '\n'.join(l for l in summary.split('\n') if not l.strip().startswith('#'))

# ── 1. the six reads happen together ──────────────────────────────────────
check('every chain is read at once, so the wait is the slowest single network '
      'rather than the sum of six', 'ThreadPoolExecutor' in code)
check('...with no balance read left in a plain loop, which is what made the '
      'page wait for all six in turn',
      not re.search(r'for chain in EVM_CHAINS:\s*\n(?:.*\n)?\s*.*get_evm_usdc_balance', code))
check('...including Solana, which was the first of the six and blocked the '
      'rest before any of them started',
      '_get_solana_usdc_balance' in code
      and code.index('ThreadPoolExecutor') < code.index('results.get')
      and 'jobs' in code)
check('...and one slow chain cannot hang the page indefinitely',
      'timeout=' in code and '.result(' in code)

# ── 2. a chain that fails must not be remembered as empty ─────────────────
check('a chain that will not answer reads as zero for this one response but is '
      'NOT cached as zero — one flaky RPC must not hide real money for the '
      'whole cache window',
      re.search(r'except Exception[\s\S]{0,320}?return 0\.0', code)
      and code.index('return 0.0') < code.index('_usdc_cache_put(key, val)'))

# ── 3. asking twice is free, and the refresh button still means refresh ───
check('balances are cached briefly, so the page load and the poll behind it '
      'do not each pay for six network reads',
      '_usdc_cache_get(' in code and '_usdc_cache_put(' in code)
ttl = re.search(r'_USDC_CACHE_TTL\s*=\s*(\d+)', SRC)
check('...for seconds, not minutes — a real deposit has to show up',
      ttl and 1 <= int(ttl.group(1)) <= 30)
check('the refresh button bypasses it entirely. Somebody who just deposited '
      'is pressing it precisely because they expect the number to have '
      'changed', "request.args.get('bust')" in code and 'if not bust:' in code)
check('...under a lock, since gunicorn serves this from several threads',
      '_usdc_cache_lock' in SRC)
check('...and bounded, so it cannot grow a row per wallet forever',
      re.search(r'len\(_usdc_cache\) > \d+', SRC))

# ── 4. the bridge button ──────────────────────────────────────────────────
# The MARKUP, not the stylesheet. Splitting on the bare class name landed on
# the CSS rule of the same name, which contains no buttons at all -- so the
# "Bridge is gone" check passed without ever looking at the action row.
_open = '<div class="wlt-hero-actions">'
assert _open in WALLET, 'the action row markup moved'
actions = WALLET.split(_open)[1].split('</div>')[0]
check('the action row no longer offers Bridge as a manual chore',
      '_modalBridge()' not in actions)
check('...while Deposit, Send and Swap — the three people actually use — stay',
      all(x in actions for x in ('_modalDeposit()', '_modalSend()', 'openSwapModal()')))
check('the automatic bridge is untouched: buying on a chain with no balance '
      'still moves funds by itself and completes the purchase',
      '_maybe_start_auto_bridge_for_buy' in SRC
      and 'auto_buy_token_address' in fn('_maybe_start_auto_bridge_for_buy'))
check('...and the endpoints behind it are still there, since that is what the '
      'automatic path calls',
      "'/api/bridge/quote'" in SRC or '/api/bridge/quote' in SRC)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
