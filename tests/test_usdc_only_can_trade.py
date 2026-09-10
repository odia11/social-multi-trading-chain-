"""A wallet holding only USDC has to be able to trade.

That is the whole point of funding everything in USDC, and on Solana it did
not work. Two separate refusals stood in the way, both left over from when
trades were paid for in SOL.

IN THE PAGE
manualBuy refused when the rendered SOL balance was under 0.01, and the bot
would not start under 0.02. Both were the browser deciding, from a number on
screen, that a trade could not happen -- for a trade that does not spend SOL
at all. A USDC-only wallet never reached the server, and was told to go and
deposit SOL.

ON THE SERVER
_solana_buy_flow read the SOL balance and refused outright. The EVM side has
called _ensure_evm_gas before every buy from the start; Solana has the
identical helper -- it tops the trading wallet up from the platform sponsor
-- and simply never called it here.

So: the page asks, the server decides, and the server asks the sponsor before
it refuses anyone.
"""
import ast
import re
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
JS = open(REPO + '/static/dashboard.js', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''

def code(js):
    out, blk = [], False
    for line in js.split('\n'):
        t = line.strip()
        if blk:
            if '*/' in t: blk = False
            continue
        if t.startswith('/*'):
            blk = '*/' not in t
            continue
        if t.startswith('//'):
            continue
        out.append(re.sub(r'//.*$', '', line))
    return '\n'.join(out)

JSC = code(JS)

# ── 1. the page stops guessing ────────────────────────────────────────────
buy = JSC[JSC.index('async function manualBuy'):]
buy = buy[:buy.index('async function manualSell')]
check('the Buy button no longer refuses on a SOL balance it read off the '
      'screen — a trade funded in USDC was being blocked before the server '
      'was ever asked',
      'Insufficient SOL balance' not in JSC and 's-sol' not in buy)
check('...and it still asks the server, rather than the check simply being '
      'deleted along with the request', "'/api/manual_buy'" in buy)
check('...and shows whatever the server says, which is the message that knows '
      'which balance is actually short', 'r?.msg' in buy or 'r.msg' in buy)

check('starting the bot no longer requires SOL in the wallet either',
      'you need at least 0.02 SOL' not in JSC)

# The rule, not the two instances: no page-side balance number may veto a
# trade, because the page cannot know whether the sponsor will step in.
# Matching every mention of the element flagged the code that RENDERS it,
# which is not a veto and never was. The shape that matters is reading its
# text back out as a number -- that is the page turning a rendered figure
# into a decision it has no business making.
vetoes = [l.strip() for l in JSC.split('\n')
          if re.search(r"parseFloat\([^)]*s-sol[^)]*textContent", l)]
for v in vetoes:
    print('   still vetoes on the rendered balance: ' + v[:90])
check('no remaining code reads the on-screen SOL figure back as a number to '
      'decide whether a trade may happen', not vetoes)

# ── 2. the server asks the sponsor before refusing ────────────────────────
flow = fn('_solana_buy_flow')
check('the Solana buy asks the gas sponsor to top the wallet up',
      '_ensure_solana_gas(' in flow)
check('...only when the wallet is actually short, so a funded wallet does not '
      'bother the sponsor on every buy',
      flow.index('us_sol < SOL_NETWORK_RESERVE') < flow.index('_ensure_solana_gas('))
check('...and re-reads the balance afterwards rather than trusting the return '
      'value, because a grant is only real once the balance says so',
      flow.count('_get_user_sol(trading_wallet)') >= 2
      and flow.index('_ensure_solana_gas(') < flow.rindex('_get_user_sol(trading_wallet)'))
check('...refusing only after that, and still naming which balance is short',
      'Not enough SOL for network fees' in flow
      and flow.rindex('_get_user_sol(trading_wallet)') < flow.index('Not enough SOL for network fees'))
check('...and saying plainly that the trade itself is funded in USDC, since '
      'somebody reading "not enough SOL" will otherwise assume it is the '
      'trade that is short', 'this is only the fee' in flow)
check('a failure inside the top-up does not take the buy down with it — it '
      'falls through to the same refusal',
      re.search(r'except Exception[\s\S]{0,260}?_gas_ok, _gas_msg = False', flow))

# ── 3. and the BOT, which kept its own copy of the old rule ───────────────
# Found in a live deploy log: two running bots printing "SKIPPING BUYS --
# insufficient SOL (0.0)" every cycle. The manual path had been fixed; the
# bot loop had a separate gate that never asked the sponsor, so their owners
# were stuck with a bot that scanned forever and bought nothing.
loop = fn('user_trader_loop')
check('the bot asks the gas sponsor before skipping a cycle for lack of SOL, '
      'instead of writing the same refusal into the log forever',
      '_ensure_solana_gas(' in loop)
check('...only when the wallet has something to trade with. Granting SOL to a '
      'wallet holding no USDC spends float on a bot that still cannot buy — '
      'the same judgement gas_manager already makes',
      'us_solana_avail >= 1' in loop
      and loop.index('us_solana_avail >= 1') < loop.index('_ensure_solana_gas('))
check('...and re-reads the balance before deciding, so the skip reflects what '
      'the wallet has after the grant rather than before',
      re.search(r'_ensure_solana_gas\([\s\S]{0,200}?us_sol = _get_user_sol', loop))
check('...with the skip still there for a wallet the sponsor could not help — '
      'the gate is not removed, it is asked later',
      'SKIPPING BUYS' in loop)
check('...and a failure in the top-up does not kill the trading loop',
      re.search(r'except Exception as _e[\s\S]{0,160}?gas top-up failed', loop))

# ── 3. this is what the EVM side already did ──────────────────────────────
check('the EVM buy has always done this, which is why only Solana was broken',
      '_ensure_evm_gas(' in fn('_evm_buy_flow'))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
