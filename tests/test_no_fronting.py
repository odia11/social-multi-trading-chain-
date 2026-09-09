"""OrcAgent puts up nothing. Users fund their own gas.

The brief said the platform subsidises nothing, and the first reading of
that was "front it, then charge it back" — net zero on paper, but it still
means parking real money on six chains and carrying the risk of a grant that
never comes back. The plainer reading is the right one, and it is what the
owner asked for: no fronting at all.

Nothing is lost by it. A wallet low on gas already tops itself up from the
user's own stablecoin on that chain; a wallet at literal zero bridges a
little of the user's own SOL. Sponsorship was only ever a faster route for
the second case — and the only one that costs the platform anything.

What must stay true: with fronting off, no sponsor transfer can happen even
if a key is present, and gas is still CHARGED to the user, because it is
still a real cost of their trade.
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


# ── the rule ──
check('there is one named rule for whether the platform ever fronts anything',
      'ORCAGENT_FRONTS_GAS' in SRC)
check("...and it is OFF unless explicitly switched on, so a deployment that "
      'says nothing does not quietly start lending money',
      "os.getenv('ORCAGENT_FRONTS_GAS', '')" in SRC
      and "in ('1', 'true', 'yes', 'on')" in SRC)

# ── it is refused at the source, not merely unfunded ──
evm = fn('_sponsor_evm_gas')
check('the EVM sponsor refuses BEFORE it looks at whether a key exists. An '
      'empty wallet is an accident; a rule is a decision',
      'if not ORCAGENT_FRONTS_GAS' in evm
      and evm.index('ORCAGENT_FRONTS_GAS') < evm.index('GAS_SPONSOR_PRIVATE_KEY'))
check('...and says why, so the fallback log reads as a choice rather than a '
      'failure', 'does not front gas' in evm)

sol = fn('_ensure_solana_gas')
check('the Solana side follows the same rule', 'not ORCAGENT_FRONTS_GAS' in sol)

# ── the user still pays, because it is still their cost ──
q = fn('_te_needs_sponsored_gas')
check('with fronting off nothing is LABELLED sponsored — gas is simply the '
      "user's cost, which is how the quote already prices it",
      'if not ORCAGENT_FRONTS_GAS' in q)
check('...and that label never decided whether gas was charged, only whether it '
      'was marked as fronted', 'never whether it was' in q or 'never whether' in q)

# ── the paths that DO fund a wallet are the user's own money ──
gas = fn('_ensure_evm_gas_locked')
check("a wallet low on gas is topped up from the user's own stablecoin on that "
      'chain', '_execute_evm_gas_topup' in gas and 'get_evm_usdc_balance' in gas)
check("a wallet at literal zero bridges a little of the user's own SOL",
      '_bootstrap_evm_gas_via_bridge' in gas)
check('...and the log says that is what is happening, rather than reporting the '
      'sponsor as unavailable', "user's own SOL instead" in gas)
check('a wallet with nothing at all is an honest dead end, worded as an '
      'instruction', 'deposit a little' in gas)

# ── the accounting stays ──
check('the subsidy accounting is kept: it reports what past grants cost and '
      'whether they came back, which is still worth knowing even though no new '
      'ones are made', 'te_subsidy.subsidy_report' in SRC)

# ── the check must not report the expected state as a problem ──────────────
V = open(REPO + '/tools/verify_live.py').read()
check('the live check says fronting is off, rather than listing six zero '
      'balances that read like something is broken',
      'OrcAgent fronts nothing' in V
      and 'meant to be' in V and 'not a problem to fix' in V)
check('...and the sponsor balances are skipped rather than reported as empty',
      V.count("not used (ORCAGENT_FRONTS_GAS is off)") == 2)

# ── the dead end has to name the way out, and the cheap one first ──────────
# With fronting off, a wallet at zero native gas is a real block. The message
# offered one route: deposit $5 of SOL to be bridged. That was advice from
# when the sponsor existed and the bridge was a rare fallback — telling
# someone to move $5 through a bridge to enable a $1 trade is not the best
# available answer, and it is now the ONLY one the app was offering.
boot = fn('_bootstrap_evm_gas_via_bridge')
check('the dead end offers sending the chain\'s own gas token directly',
      'Send a ' in boot and 'a few cents is enough' in boot)
check('...before the bridge route, because a few cents beats moving $5 of SOL '
      'to enable a $1 trade',
      boot.index('a few cents is enough') < boot.index('of SOL and it will'))
check('...while keeping the bridge, which works from capital the user already '
      'holds on Solana', 'GAS_BOOTSTRAP_SOL_USD' in boot)
check('...and names the wallet to send to, rather than leaving the user to find '
      'it', 'evm_address or' in boot)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
