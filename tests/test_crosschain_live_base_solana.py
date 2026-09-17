"""The first real Base -> Solana route, pinned.

This is the actual response api.0x.org returned to the production server on
2026-09-17, captured read-only. Everything asserted here is a fact about that
response, not about a schema or an example -- so if 0x changes any of it, this
is what says so.

WHY EACH OF THESE IS WORTH PINNING
Three of the four things the first live run reported turned out to be about
this repository rather than about 0x: the envelope was right all along, the
quoteId IS present, and the allowanceTarget IS canonical. The one genuinely
new fact is the economics -- a $2 bridge costs 11% -- and that is the one a
user would actually feel.
"""
import json
import os
import sys
from decimal import Decimal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from trade_engine import crosschain as X            # noqa: E402
from trade_engine import registry as R              # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


FX = os.path.join(REPO, 'tests', 'fixtures', '0x', 'quote_base_to_solana.json')
if not os.path.isfile(FX):
    print('NOTE  the live Base -> Solana fixture is not present; nothing to pin.')
    sys.exit(0)

fx = json.load(open(FX))
data = fx['response']
q = data['quotes'][0]

ALLOWANCE_HOLDER_CANCUN = '0x0000000000001ff3684f28c67538d4d072c22734'


def parse(**over):
    body = json.loads(json.dumps(data))
    for path, value in over.items():
        node = body
        parts = path.split('.')
        for p in parts[:-1]:
            node = node[int(p)] if p.isdigit() else node[p]
        node[parts[-1]] = value
    return X.ZeroExCrossChain(lambda **kw: body, lambda **kw: {}).get_quote(
        source_chain='base', destination_chain='solana',
        source_amount_raw=2_000_000, origin_address=fx['origin_address'],
        destination_address=fx['destination_address'])


# ── the envelope, settled ────────────────────────────────────────────────
check('the live envelope is "quotes" — the shape this parser has accepted all '
      'along, and "routes" never appeared',
      isinstance(data.get('quotes'), list) and 'routes' not in data)


# ── the two identifiers ──────────────────────────────────────────────────
check('the live quote DOES carry a quoteId', q['quoteId'] == '0x7a0f477248b07297e32688d176f4c808')
check('...and a separate top-level zid', data['zid'] == '0x7a0f477248b07297e32688d1')
check('...and the quoteId is the zid plus eight more hex characters. They look '
      'interchangeable at a glance, which is precisely how `quoteId or zid` '
      'came to be written and why it was wrong',
      q['quoteId'].startswith(data['zid']) and q['quoteId'] != data['zid'])

r = parse()
check('the parser keeps them apart on the route', r.quote_id == q['quoteId']
      and r.zid == data['zid'] and r.quote_id != r.zid)


# ── THE ALLOWANCE TARGET, identified ─────────────────────────────────────
# 0x-settler's README lists this address as AllowanceHolder for Cancun-hardfork
# chains -- "Ethereum mainnet, Polygon, Base, Optimism, Arbitrum, and others".
# Base is one of them. It is a contract 0x publishes as an allowance holder,
# which is what makes approving it correct rather than merely accepted.
check('the live allowanceTarget is AllowanceHolder (Cancun), the contract 0x '
      'publishes for exactly this purpose on Base',
      data['allowanceTarget'].lower() == ALLOWANCE_HOLDER_CANCUN)
check('...and it was ALREADY in the allowlist — nothing was added to make this '
      'pass, which was the one thing not to do',
      ALLOWANCE_HOLDER_CANCUN in X.CANONICAL_ALLOWANCE_TARGETS)
check('...and it is not the Settler registry',
      data['allowanceTarget'].lower() != X.ZEROX_SETTLER_REGISTRY)
check('the top-level allowanceTarget and issues.allowance.spender agree, so '
      'there is no ambiguity about what would be approved',
      data['allowanceTarget'].lower() == q['issues']['allowance']['spender'].lower())

# The live route calls the same contract it asks to be approved. That is the
# AllowanceHolder pattern and it is legitimate -- but ONLY because this
# address is canonical. Any other contract doing it is the Settler shape.
check('the live route calls the very contract it asks to approve — the '
      'AllowanceHolder pattern, allowed here only because the address is one '
      '0x publishes',
      q['transaction']['details']['to'].lower() == data['allowanceTarget'].lower())

fake = q['transaction']['details']['to']
try:
    parse(**{'allowanceTarget': '0x2222222222222222222222222222222222222222',
             'quotes.0.issues.allowance.spender': '0x2222222222222222222222222222222222222222',
             'quotes.0.transaction.details.to': '0x2222222222222222222222222222222222222222'})
    check('...and an UNPUBLISHED contract doing the same thing is refused', False)
except X.CrossChainError:
    check('...and an UNPUBLISHED contract doing the same thing is refused, '
          'because "approve the thing you are calling" is also the shape of '
          'the Settler mistake', True)


# ── the ephemeral signer, answered by the response itself ────────────────
eph = X.ephemeral_signer_requirement(q, data)
check('the live Base -> Solana response asks for NO ephemeral co-signer — the '
      'field does not appear at all',
      eph['required'] is False and eph['path'] == '')
check('...which matches 0x\'s own EVM -> Solana example, where the whole trade '
      'is signed with the EVM key and no Solana keypair is created. The '
      'earlier "required: true" was this repository\'s detector, not 0x',
      'ephemeral' not in json.dumps(data).lower())


# ── the route, as the engine reads it ────────────────────────────────────
check('the bridge is served by relay on this route', r.bridge_provider == 'relay')
check('it sells Base USDC', r.source_token.lower() == R.CHAINS['base'].stable.address.lower())
check('...and delivers Solana USDC, so the destination swap has the asset it '
      'is going to spend',
      r.destination_token == R.CHAINS['solana'].stable.address)
check('the amounts are read exactly', r.source_amount_raw == 2_000_000
      and r.expected_out_raw == 1_798_148 and r.minimum_out_raw == 1_780_167)
check('an allowance really is needed on this route', r.needs_allowance is True)


# ── THE ECONOMICS, which is the genuinely new finding ────────────────────
loss = r.loss_usd()
check('the live bridge cost on a $2 trade is $0.22', str(loss) == '0.22')
check('...which is ELEVEN PERCENT of the trade. A bridge\'s costs are mostly '
      'fixed, so the percentage is a fact about the SIZE, not about the route',
      Decimal('10') < (loss / Decimal('2')) * 100 < Decimal('12'))
check('...and it is charged to the user, as one line the quote can show',
      [c.kind for c in r.cost_lines()] == ['bridge_fee']
      and r.cost_lines()[0].payer == 'user')


# ── the provider's own gas figure ────────────────────────────────────────
check('the live response gives gasCosts as an object with totalNetworkFee in '
      'wei, not a list', isinstance(r.gas_costs_raw, dict)
      and r.gas_costs_raw.get('totalNetworkFee') == '1152682591024')


# ── the fixture is for PARSING, never for signing ────────────────────────
# The capture redacts long strings, so the calldata in it is truncated. It is
# fine for checking that the parser reads the response; it is not a
# transaction and must never be mistaken for one.
check('the captured calldata is truncated by the redactor, so this fixture can '
      'verify parsing but could never be broadcast — worth stating, because a '
      'fixture that looks executable is a trap',
      '[' in q['transaction']['details']['data']
      and 'chars]' in q['transaction']['details']['data'])


# ── nothing in the fixture is a secret ───────────────────────────────────
blob = json.dumps(fx).lower()
check('the captured fixture contains no key, seed or signature material',
      not any(w in blob for w in ('privatekey', 'private_key', 'mnemonic',
                                  'seed', 'apikey', 'api_key', 'secret')))
check('...and the addresses in it are 0x\'s own published example addresses, '
      'not a real user\'s wallet',
      fx['origin_address'] == '0xABf40AADf960e20B4283dc5A06387A429Ba02456'
      and fx['destination_address'] == '9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ')

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
