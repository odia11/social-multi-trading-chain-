"""One currency for the user: USDC, on every chain.

THE TWO FACTS, AND WHY THEY ARE NOT THE SAME
Robinhood Chain has no USDC. Bridge some there and it converts to USDG
(Global Dollar, Paxos). That made the buy panel read "YOU SPEND AT MOST
USDG", which was defended as honesty -- USDC does not exist on that chain,
so calling it USDC would be a lie.

Right about the chain, wrong about the question. Two different facts:

  what MOVES on-chain   USDG on Robinhood Chain. Logs, the swap routing and
                        anything you would take to a block explorer need
                        this, or a transaction cannot be found again.

  what the USER SPENDS  USDC, everywhere. They never hold, choose, or
                        deposit USDG. They spend their USDC and the app
                        bridges it there, where it converts on arrival.

So showing USDC is not relabelling USDG. It names the thing the person
actually spent, and leaves the on-chain token named accurately where the
on-chain token is what matters. The background conversion already existed:
_maybe_start_auto_bridge_for_buy finds a chain with enough and bridges it,
with the buy riding along.

WHAT THIS FILE GUARDS
That the split does not collapse in either direction: no user-facing string
may name USDG, and no log or routing path may be "tidied up" into claiming
USDC where USDG is what really moved.
"""
import ast
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


# ── one function answers "what is the user spending" ──────────────────────
check('there is one named answer to what a user spends, rather than the '
      'question being re-derived at each call site',
      'def user_currency_label(' in SRC)

_ns = {}
exec(fn('user_currency_label'), _ns)
label = _ns['user_currency_label']
check('every EVM chain reads USDC, Robinhood Chain included — that is the '
      'whole point',
      all(label(c) == 'USDC'
          for c in ('bsc', 'base', 'arbitrum', 'polygon', 'robinhood')))
check('...and Solana too, since USDC is what a Solana trade is funded with '
      'as well', label('solana') == 'USDC')
check('SOL mode is the one exception, because that IS a real user choice and '
      'not plumbing', label('solana', 'SOL') == 'SOL')
check('...and it is the mode that decides it, not the chain — asking about '
      'Solana without SOL mode still answers USDC',
      label('solana', 'USDC') == 'USDC' and label('SOLANA', 'sol') == 'SOL')

# ── nothing a user reads may name USDG ────────────────────────────────────
for name, why in [
    ('_maybe_start_auto_bridge_for_buy',
     'the message when no chain has enough to bridge from'),
    ('_execute_evm_gas_topup', 'the gas top-up shortfall'),
    ('_sponsor_evm_gas', 'the reason a sponsored grant was refused'),
]:
    body = fn(name)
    check(f'{why} names the currency the user spends, not the settlement token',
          'user_currency_label(' in body)

check("the label carried into notifications and trade text comes from it too",
      "currency_label = 'SOL' if chain == 'solana' else user_currency_label(chain)" in SRC)
check("...as does a trade's P&L currency wherever it is displayed",
      fn('_trade_currency_symbol').count('user_currency_label(') == 1)

# ── the on-chain symbol survives, because a log is not a screen ───────────
check('usdc_symbol still says USDG for Robinhood Chain — a transaction has to '
      'stay findable on the explorer', "'usdc_symbol': 'USDG'" in SRC)
check('...and the swap itself still names the token it is really selling, or '
      'the route would be described wrong in its own record',
      "sell_token, buy_token, sell_symbol = usdc_addr, token_cs, usdc_symbol" in SRC)
check('...and the gas top-up log line still reports what actually moved',
      "{usdc_amount} {usdc_symbol} -> {native_symbol}" in SRC)

# ── the background conversion this rests on has to exist ──────────────────
buy = fn('_evm_buy_flow')
check('a buy whose chain lacks the balance starts a bridge instead of failing '
      '— this is what makes "you spend USDC" true on a chain that holds none',
      '_maybe_start_auto_bridge_for_buy(' in buy)
bridge = fn('_maybe_start_auto_bridge_for_buy')
check('...bridging into the destination chain\'s OWN token address, so the '
      'conversion to USDG happens by routing rather than by pretending',
      "EVM_CHAINS[dest_chain]['usdc']" in bridge)
check('...and the buy rides along on that bridge rather than asking the user '
      'to come back and press Buy again', 'auto_buy_token_address=' in bridge)

# ── the frontend says the same thing ──────────────────────────────────────
LMP = open(REPO + '/static/live-market-pro.js').read()
check('the buy panel labels every EVM chain USDC',
      "function evmCurrencyLabel(chain){ return 'USDC'; }" in LMP)
check('...with no per-chain override left to drift back out of step',
      'EVM_CURRENCY_LABELS' not in LMP)

WAL = open(REPO + '/templates/wallet.html').read()
check('the bridge form shows USDC for both sides',
      "var destSym='USDC'" in WAL and "var originSym='USDC'" in WAL)
check('...and its amount field too, whichever chain is selected',
      "sym.textContent = 'USDC'" in WAL)
check('...and the blurb no longer explains a token the user never handles',
      'USDG on Robinhood Chain' not in WAL)

# No user-visible string anywhere may still say USDG. Comments may, and must:
# they are where the reason lives.
def _strings_naming_usdg(text):
    out = []
    for line in text.splitlines():
        code = line.split('//')[0] if '//' in line else line
        code = code.split('#')[0] if '#' in code else code
        if 'USDG' in code:
            out.append(line.strip())
    return out

for path in ('/templates/wallet.html', '/static/live-market-pro.js',
             '/static/token-card.js'):
    leaks = _strings_naming_usdg(open(REPO + path).read())
    check(f'no USDG reaches the screen from {path.rsplit("/", 1)[-1]}', not leaks)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
