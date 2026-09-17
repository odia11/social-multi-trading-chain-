"""A bridge should not refuse gas that the rest of the app would have found.

WHAT WAS WRONG
Every same-chain EVM trade climbs a ladder before it gives up on gas:
_ensure_evm_gas() tries the sponsor, then a small bridge of the user's own
SOL, then a swap of the user's own USDC on that chain. A user with USDC on
Base and no ETH therefore CAN trade on Base -- the app funds the fee out of
what they already hold, and the trade's own quote carries the cost.

The cross-chain path did not climb it. It asked "is there gas?" instead of
"can this wallet get gas?", and answered a user with $30 of USDC on Base that
they could not bridge. Same wallet, same money, opposite answer, depending on
which button they pressed.

WHAT THIS IS NOT
Not a subsidy. Every rung of that ladder is the user's own money; OrcAgent
fronts nothing, and this deployment does not even run a sponsor. That rule is
checked here too, because "make it easier" is exactly the pressure under
which somebody quietly starts paying users' gas.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


SRC = open(os.path.join(REPO, 'dashboard.py')).read()

# The block under test, isolated so a match elsewhere in a 32k-line file
# cannot make this pass by accident.
m = re.search(r"gas_req = _cc_gas_requirement\(wallet, source_chain, route\)"
              r"(.*?)'native_gas': gas_req\}\), 400", SRC, re.S)
check('the cross-chain execute path still has its gas gate', m is not None)
BLOCK = m.group(1) if m else ''

check('a short EVM origin now climbs the same ladder every other EVM trade '
      'climbs, instead of being refused outright',
      '_ensure_evm_gas(' in BLOCK and 'source_chain in EVM_CHAINS' in BLOCK)
check('...using the trading key through _use_key, so the key is opened for '
      'exactly this and closed again',
      'with _use_key(' in BLOCK)
check('...against the address that actually holds the money on that chain',
      '_cc_taker_address(wallet, source_chain)' in BLOCK)

check('when the ladder succeeds the requirement is RE-READ from chain rather '
      'than assumed, because the number that matters is the one on chain',
      BLOCK.count('_cc_gas_requirement(wallet, source_chain, route)') >= 1
      and 'Re-read rather than assume' in BLOCK)

check('when a bootstrap bridge is on its way the user is told so, with the '
      'bridge id, and gets 202 rather than a refusal — it is not a failure, '
      'it is a wait',
      "'pending_gas': True" in BLOCK and "'bridge_id': _bridge_id" in BLOCK
      and '202' in BLOCK and "'code': 'GAS_ON_THE_WAY'" in BLOCK)
check('...and the message says what to do next rather than only what '
      'happened', 'ask for' in BLOCK and 'fresh quote' in BLOCK)

check('when the ladder genuinely cannot fund it, the original refusal still '
      'stands — with the amount needed, and no pretending',
      "'code': gas_req['code']" in SRC and "'native_gas': gas_req" in SRC)

# ── the line that must not move ──────────────────────────────────────────
check('OrcAgent still fronts nothing: the comment says it and the refusal '
      'text still says it to the user',
      'Nothing is fronted by OrcAgent here' in BLOCK
      and 'OrcAgent does not pay it for you' in SRC)
check('...and the Solana origin path is untouched — this is an EVM ladder '
      'and Solana has no equivalent here',
      'source_chain in EVM_CHAINS' in BLOCK)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
