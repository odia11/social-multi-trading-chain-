"""OrcAgent fronts the gas. The user still pays for it.

Those two sentences are not in tension, and keeping them both true is the
whole point of this file.

WHY IT IS ON
A user who holds only USDC has no native token on Arbitrum, Base, BSC or
Polygon. They cannot pay for their first transaction there -- including the
transaction that would convert some of their own stablecoin into gas. Left
alone, that user is told to go and acquire gas somewhere else before they may
trade, which is exactly the errand this platform exists to remove. So the
sponsor wallet puts up the native token.

WHY THAT IS NOT A SUBSIDY
Since phase 4 the gas is a line in the trade's own quote, charged to the user
out of the USDC they were spending anyway. The sponsor is a payment rail: the
money goes out and comes back on the same trade. What it costs the platform is
float, not gas.

WHAT MUST STAY TRUE
  * the user is charged -- a fronted cost is never a discount;
  * the rule is reversible -- ORCAGENT_FRONTS_GAS=0 makes every sponsor path
    refuse at the source rather than merely run dry;
  * the routes that spend the user's OWN money still exist, because the
    sponsor can decline (rule off, no key, anti-farming gate, empty wallet)
    and a decline must not be a dead end;
  * the accounting still reports what was fronted and whether it came back,
    which is the only way "it comes back" is a fact rather than a hope.
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


# ── the rule, and which way it points ──────────────────────────────────────
check('there is one named rule for whether the platform ever fronts anything',
      'ORCAGENT_FRONTS_GAS' in SRC)
check('...and it is ON when nothing is configured, because a user holding only '
      'USDC cannot pay for the transaction that would get them gas',
      "os.getenv(\n    'ORCAGENT_FRONTS_GAS', '').strip().lower() not in "
      "('0', 'false', 'no', 'off')" in SRC)

# The flag is evaluated the same way the app evaluates it, so this tests the
# real expression rather than a re-reading of it.
_ns = {'os': __import__('os')}
_flag_src = next(l for l in SRC.splitlines() if l.startswith('ORCAGENT_FRONTS_GAS = '))
_flag_src = SRC[SRC.index(_flag_src):]
_flag_src = _flag_src[:_flag_src.index('\n# The smallest sensible')]

def _flag(value):
    import os
    old = os.environ.get('ORCAGENT_FRONTS_GAS')
    if value is None:
        os.environ.pop('ORCAGENT_FRONTS_GAS', None)
    else:
        os.environ['ORCAGENT_FRONTS_GAS'] = value
    try:
        ns = {'os': os}
        exec(_flag_src, ns)
        return ns['ORCAGENT_FRONTS_GAS']
    finally:
        if old is None:
            os.environ.pop('ORCAGENT_FRONTS_GAS', None)
        else:
            os.environ['ORCAGENT_FRONTS_GAS'] = old

check('an unconfigured deployment fronts gas, so the product works as built '
      'without anyone having to know a variable name', _flag(None) is True)
check('...and so does one that sets it to 1', _flag('1') is True)
check('a deployment unwilling to put up the float can turn it off, and the '
      'obvious spellings all work',
      all(_flag(v) is False for v in ('0', 'false', 'no', 'off', 'OFF', ' 0 ')))
check('...while a typo does not silently disable it — anything that is not a '
      'recognised "off" leaves fronting on, which is the safe direction for a '
      'cost that is recovered anyway',
      _flag('flase') is True and _flag('') is True)

# ── off means refused at the source, not merely unfunded ───────────────────
evm = fn('_sponsor_evm_gas')
check('with the rule off, the EVM sponsor refuses BEFORE it looks at whether a '
      'key exists. An empty wallet is an accident; a rule is a decision',
      'if not ORCAGENT_FRONTS_GAS' in evm
      and evm.index('ORCAGENT_FRONTS_GAS') < evm.index('GAS_SPONSOR_PRIVATE_KEY'))
check('...and says why, so the fallback log reads as a choice rather than a '
      'failure', 'does not front gas' in evm)

sol = fn('_ensure_solana_gas')
check('the Solana side honours the same switch', 'not ORCAGENT_FRONTS_GAS' in sol)

# ── the user pays, which is what makes this a rail and not a subsidy ───────
q = fn('_te_needs_sponsored_gas')
check('the quote knows when gas will be fronted, so the cost can be labelled '
      'as such', 'if not ORCAGENT_FRONTS_GAS' in q)
check('...and that label never decided whether gas was charged, only whether it '
      'was marked as fronted', 'never whether it was' in q or 'never whether' in q)
check('...and it fails CLOSED — an unreadable balance assumes sponsorship, '
      'which can only make the quote more conservative',
      'return True' in q.split('except')[-1])

COSTS = open(REPO + '/trade_engine/costs.py').read()
check('a fronted cost is charged to the user by construction: recovered=True '
      'sets the payer to the user, and recovered=False marks OrcAgent as payer '
      'rather than hiding the loss',
      'PAYER_USER if recovered else PAYER_ORCAGENT' in COSTS)
QUOTE = open(REPO + '/trade_engine/quote.py').read()
check('...and the quote builder only ever fronts on the recovered terms, so no '
      'code path can quietly produce a gift',
      'sponsored_gas(' in QUOTE and 'recovered=False' not in QUOTE)
check('...on both pricing passes, so the cheaper route-based gas figure is '
      'recovered exactly like the conservative one it replaces',
      QUOTE.count('sponsored_gas(') == 2)

# ── a decline is not a dead end: the user's own money still works ──────────
gas = fn('_ensure_evm_gas_locked')
check("a wallet low on gas is topped up from the user's own stablecoin on that "
      'chain', '_execute_evm_gas_topup' in gas and 'get_evm_usdc_balance' in gas)
check('a wallet at literal zero asks the sponsor first, because that is the '
      'only route that does not need a transaction the wallet cannot pay for',
      gas.index('_sponsor_evm_gas') < gas.index('_bootstrap_evm_gas_via_bridge'))
check("...and falls back to bridging a little of the user's own SOL when the "
      'sponsor declines', '_bootstrap_evm_gas_via_bridge' in gas)
check('...with the log saying which of the two is happening, rather than '
      'reporting the sponsor as broken', "user's own SOL instead" in gas)
check('a wallet with nothing at all is an honest dead end, worded as an '
      'instruction', 'deposit a little' in gas)

# ── the accounting is what makes "it comes back" checkable ─────────────────
check('the subsidy accounting is kept: it reports what was fronted and whether '
      'it was recovered, which is the only evidence that float is float',
      'te_subsidy.subsidy_report' in SRC)

# ── the live check has to reflect whichever rule is in force ───────────────
V = open(REPO + '/tools/verify_live.py').read()
check('the live check reads the rule before judging the balances, so the same '
      'reading is used for the headline and the checks below it',
      '_fronting = bool(getattr(d, ' in V)
check('...saying, when fronting is on, that these wallets are float rather than '
      'an expense — the reason the owner is being asked to fund them',
      'OrcAgent fronts gas' in V and 'it comes back' in V)
check('...and still saying, when it is off, that empty wallets are the expected '
      'state rather than a fault',
      'fronts nothing' in V and 'meant to be' in V and 'a problem to fix' in V)
check('an empty sponsor wallet is now a FINDING, because with fronting on it is '
      'the thing that silently breaks the first trade of every USDC-only user',
      'top these up' in V and 'raise RuntimeError(line' in V)
check('...judged per chain against what that chain\'s gas actually costs, so a '
      'BNB balance is not measured against an ETH yardstick',
      'SPONSOR_LOW_CHEAP' in V and 'SPONSOR_LOW_NATIVE' in V)
check('...and a missing key is called out as the contradiction it is when the '
      'deployment says it fronts',
      'is not set, but this ' in V and 'deployment fronts gas' in V)
check('the checks are still skipped, not failed, where the rule is off',
      V.count("not used (ORCAGENT_FRONTS_GAS is off)") == 2)

# ── the dead end still names the way out, cheapest first ───────────────────
# Reached only once the sponsor has declined, so it is the rare case again —
# but rare is not never, and the message is what the user reads on the Buy
# panel when it happens.
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

# ── the deployment kit has to document the switch it now defaults to ───────
ENV = open(REPO + '/deploy/env.example').read()
check('the env example documents the rule, so an operator can find it without '
      'reading the source', 'ORCAGENT_FRONTS_GAS' in ENV)
check('...naming the default rather than showing a line that changes nothing '
      'when uncommented', 'ORCAGENT_FRONTS_GAS=0' in ENV)
check('...and saying what funding the sponsor wallets is FOR, since that is the '
      'one thing this rule asks of the owner',
      'float' in ENV.lower() and 'sponsor' in ENV.lower())

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
