"""Whose failure is it? That decides who gets told to do something.

WHAT A USER SAW
    Cannot trade on robinhood yet — this wallet has no ETH for network
    fees yet. Send a little ETH to it on robinhood — a few cents is
    enough — or deposit at least $5 of SOL and it will be bridged into
    ETH for you

The reason that message appeared was that OUR sponsor wallet was empty. The
user had done nothing wrong. They were handed an errand — go and acquire a
chain's native token — which is the exact errand this platform exists to
remove, on the one screen where they were trying to spend money with us.

THE RULE
The same shortfall has two very different causes and they need two different
messages:

  ours    we are meant to front the gas and cannot: no sponsor key, an empty
          sponsor wallet, an unreachable RPC. The user is told it is
          temporarily unavailable and that there is nothing for them to do.
          The operator is told, loudly, in the journal.

  theirs  ORCAGENT_FRONTS_GAS is deliberately off, so users fund their own
          gas by design. "Send a little ETH" is then the honest instruction,
          not a way of passing the buck.

It fails towards OURS. If we cannot read the sponsor's balance we do not know
the user can be helped, so we do not hand them a chore on a guess.
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


# ── the question is asked, once, by name ──────────────────────────────────
check('there is one named answer to whose failure a gas shortfall is',
      'def _gas_shortfall_is_ours(' in SRC)

blame = fn('_gas_shortfall_is_ours')
check('a deployment that deliberately does not front gas is not at fault — '
      'there the instruction to fund your own is honest',
      'if not ORCAGENT_FRONTS_GAS:\n        return False' in blame)
check('a missing sponsor key is ours, since we promised to front and cannot',
      'if not GAS_SPONSOR_PRIVATE_KEY:\n        return True' in blame)
check('an empty sponsor wallet is ours — this is the case that actually '
      'happened', 'get_balance' in blame and 'gas_price' in blame)
check('...measured against what a transaction on THAT chain costs, not a '
      'constant, since a full wallet on one chain is empty on another',
      'w3.eth.gas_price * GAS_TOPUP_TX_GAS_UNITS' in blame)
check('an unreadable balance counts as ours, because not knowing whether we '
      'can help is not a reason to hand someone a chore',
      'except Exception:\n        return True' in blame)

# ── the two messages ──────────────────────────────────────────────────────
boot = fn('_bootstrap_evm_gas_via_bridge')
check('the dead end asks whose failure it is before it says anything',
      '_gas_shortfall_is_ours(chain)' in boot)

ours = boot[boot.index('_gas_shortfall_is_ours(chain)'):]
ours = ours[:ours.index('_evm_addr_hint')]
check('when it is ours the user is told it is temporarily unavailable',
      'temporarily unavailable' in ours)
check('...and told explicitly that there is nothing for them to do, which is '
      'the whole correction', 'Nothing to do on your side' in ours)
check('...and offered something they CAN do right now instead of a dead stop',
      'another chain' in ours)
check('...with no instruction to go and acquire a gas token',
      'Send a little' not in ours and 'deposit at least' not in ours)
check('...and nothing is written to the USER\'s activity log, because it is '
      'not their business', 'add_user_log(' not in ours)
check('the OPERATOR is told instead, and told what it costs to leave it — '
      'every USDC-only user on that chain is blocked',
      'CANNOT ACTIVATE' in ours and 'every ' in ours and 'blocked' in ours)

theirs = boot[boot.index('_evm_addr_hint'):]
# The message the USER reads is the return value, not the log line above it,
# so the ordering claim is checked against that string alone.
theirs_msg = theirs[theirs.index('return False,'):]
check('when fronting is off by choice, the concrete instruction survives — '
      'this file is about WHO is asked, not about removing help',
      'Send a ' in theirs_msg and 'a few cents is' in theirs_msg)
check('...cheapest route still first, since a few cents beats bridging $5 of '
      'SOL to enable a $1 trade',
      theirs_msg.index('a few cents is') < theirs_msg.index('of SOL '))

# ── the chain is named the way a person would name it ─────────────────────
check('the messages say "Robinhood Chain", not the internal key "robinhood"',
      boot.count('SURGE_ALERT_CHAIN_NAMES.get(chain, chain)') >= 1
      and '_chain_name' in boot)
buy = fn('_evm_buy_flow')
check('...including the "Cannot trade on ... yet" prefix the buy panel adds, '
      'which is where the lowercase key was actually showing',
      'SURGE_ALERT_CHAIN_NAMES.get(chain, chain)' in buy)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
