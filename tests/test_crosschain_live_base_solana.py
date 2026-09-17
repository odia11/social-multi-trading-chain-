"""The real Base -> Solana route at $30, pinned.

This is the actual response api.0x.org returned to the production server on
2026-09-17, captured read-only, at $30 and with the transaction calldata saved
at FULL LENGTH. Everything asserted here is a fact about that response, not
about a schema or an example -- so if 0x changes any of it, this is what says
so.

WHY EACH OF THESE IS WORTH PINNING
Three of the four things the first live run reported turned out to be about
this repository rather than about 0x: the envelope was right all along, the
quoteId IS present, and the allowanceTarget IS canonical. The fourth was the
economics, and it was a fact about SIZE: the same route that cost 11% of a $2
trade costs 1.87% of a $30 one. Both numbers are pinned in this repository's
history for exactly that reason.

The calldata is the part that matters most here. An earlier capture was saved
while the redactor still shortened long strings, so its transaction ended
mid-argument and could only be validated against a reconstruction. This one is
the real bytes, so every calldata assertion below reads what 0x actually sent.
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

BASE_USDC = R.CHAINS['base'].stable.address
OPERATOR = '0x7d19077317b7574cd01aafa143e5e09f0f4df466'
SELL_AMOUNT = 30_000_000

LIVE_CALLDATA = q['transaction']['details']['data']


def _w_addr(a):
    return a.lower().replace('0x', '').rjust(64, '0')


def _w_int(n):
    return format(int(n), '064x')


def tamper(word=None, value=None, selector=None):
    """The live calldata with ONE argument changed.

    The bytes are real, so a negative test does not have to reconstruct a
    transaction -- it edits a single 32-byte word of the one 0x sent and
    leaves everything else exactly as captured. Word 0 is the operator, 1 the
    token, 2 the amount, 3 the target.

    This is used to exercise the validator. The result is NOT a transaction
    and is never signed.
    """
    body = LIVE_CALLDATA[2:]
    head, args = body[:8], body[8:]
    if selector is not None:
        head = selector.replace('0x', '')
    if word is not None:
        at = word * 64
        args = args[:at] + value + args[at + 64:]
    return '0x' + head + args


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
        source_amount_raw=SELL_AMOUNT, origin_address=fx['origin_address'],
        destination_address=fx['destination_address'])


r0 = parse()

# ── the envelope, settled ────────────────────────────────────────────────
check('the live envelope is "quotes" — the shape this parser has accepted all '
      'along, and "routes" never appeared',
      isinstance(data.get('quotes'), list) and 'routes' not in data)
check('the live quote reports liquidity for Base -> Solana',
      data.get('liquidityAvailable') is True)
# The live response carries NO simulationIncomplete field at all -- not
# `false`, absent. That is 0x declining to raise the flag rather than 0x
# asserting a successful simulation, and the difference is worth pinning: the
# parser must read "absent" as "not flagged" and never as "simulated", and it
# must only ever set the route's flag on an explicit true.
check('the live response raises no simulationIncomplete flag — the field is '
      'absent rather than false, on the quote and on the envelope alike',
      q.get('simulationIncomplete') is None
      and data.get('simulationIncomplete') is None)
check('...so the parsed route reads simulation_incomplete as False, because '
      'only an explicit true sets it', r0.simulation_incomplete is False)
check('...and an explicit true IS carried through, so preflight can refuse to '
      'sign off a quote the provider could not dry-run',
      parse(**{'quotes.0.simulationIncomplete': True}).simulation_incomplete is True)


# ── the two identifiers ──────────────────────────────────────────────────
check('the live quote DOES carry a quoteId',
      q['quoteId'] == '0x07dab35a87e2c7dc4f01b20f76f4c808')
check('...and a separate top-level zid', data['zid'] == '0x07dab35a87e2c7dc4f01b20f')
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


# ── THE CALLDATA: what the transaction would actually do ─────────────────
# Everything above reads the quote's own FIELDS. This reads the bytes, which
# is the only account that settles.
#
# The selector was verified by keccak, not read off a comment:
#   keccak("exec(address,address,uint256,address,bytes)")[:4] == 0x2213bc0b
# That is AllowanceHolder.exec, which pulls `amount` of `token` from the
# caller, grants `operator` a TRANSIENT allowance for exactly that, calls
# `target`, and clears it. So the blast radius of the whole transaction is
# (token, amount) -- two arguments in plain sight at the front.
check('the captured calldata is the FULL transaction, not a shortened one — '
      'no redaction marker, even length, and long enough to carry the bridge '
      'payload',
      LIVE_CALLDATA.startswith('0x') and 'chars]' not in LIVE_CALLDATA
      and len(LIVE_CALLDATA) == 2954 and (len(LIVE_CALLDATA) - 2) % 2 == 0)
check('the live calldata selector is AllowanceHolder.exec, confirmed by '
      'keccak of the signature rather than by assumption',
      LIVE_CALLDATA[:10] == X.ALLOWANCE_HOLDER_EXEC_SELECTOR)

_dec = X.decode_allowance_holder_exec(LIVE_CALLDATA)
check('...the operator it grants a transient allowance to is 0x\'s settler for '
      'this route, and it is not the token and not the allowance contract',
      _dec['operator'].lower() == OPERATOR
      and _dec['operator'].lower() not in (BASE_USDC.lower(),
                                           ALLOWANCE_HOLDER_CANCUN))
check('...the token it would pull is Base USDC, matching the quote',
      _dec['token'].lower() == BASE_USDC.lower())
check('...and the amount it would pull is exactly the sellAmount, which is '
      'the check that would catch a route quoting $30 and encoding $30000 — '
      'every field-based check passes such a route',
      _dec['amount'] == SELL_AMOUNT == int(q['sellAmount']))
check('...and the contract it calls is the same operator, so nothing else is '
      'named anywhere in the arguments the allowance covers',
      _dec['target'].lower() == OPERATOR)

check('the real captured calldata passes validation end to end — this is the '
      'live transaction, not a reconstruction of one',
      X.verify_source_calldata(r)['checked'] is True)

# A partially readable transaction is not one to sign. The live capture is
# complete now, so this is checked by shortening it here rather than by
# relying on a fixture that happened to be truncated.
try:
    parse(**{'quotes.0.transaction.details.data': LIVE_CALLDATA[:200] + '...[2954 chars]'})
    check('...while a TRUNCATED calldata is still refused', False)
except X.RouteRejected as e:
    check('...while a TRUNCATED calldata is still refused rather than waved '
          'through — a transaction that cannot be fully read is not one to '
          'sign', 'truncated' in str(e) or 'not a number' in str(e)
          or 'length' in str(e).lower())

for label, kw in (
        ('a different token',
         {'word': 1, 'value': _w_addr('0x4200000000000000000000000000000000000006')}),
        ('a thousand times the amount', {'word': 2, 'value': _w_int(30_000_000_000)}),
        ('an operator that is the token itself', {'word': 0, 'value': _w_addr(BASE_USDC)}),
        ('a different function on the allowance contract', {'selector': '0xa9059cbb'})):
    try:
        parse(**{'quotes.0.transaction.details.data': tamper(**kw)})
        check(f'calldata naming {label} is refused', False)
    except X.RouteRejected:
        check(f'calldata naming {label} is refused', True)


# ── the route, as the engine reads it ────────────────────────────────────
check('the bridge is served by relay on this route', r.bridge_provider == 'relay')
check('it sells Base USDC', r.source_token.lower() == R.CHAINS['base'].stable.address.lower())
check('...and delivers Solana USDC, so the destination swap has the asset it '
      'is going to spend',
      r.destination_token == R.CHAINS['solana'].stable.address)
check('the amounts are read exactly', r.source_amount_raw == SELL_AMOUNT
      and r.expected_out_raw == 29_744_092 and r.minimum_out_raw == 29_446_652)
check('an allowance really is needed on this route', r.needs_allowance is True)


# ── THE ECONOMICS, at a size a user would actually trade ─────────────────
loss = r.loss_usd()
check('the live bridge cost on a $30 trade is $0.56', str(loss) == '0.56')
pct = (loss / Decimal('30')) * 100
check('...which is UNDER TWO PERCENT of the trade — the same route that cost '
      '11% of $2. A bridge\'s costs are mostly fixed, so the percentage is a '
      'fact about the SIZE, not about the route',
      Decimal('1.5') < pct < Decimal('2'))
check('...and it therefore clears the 5% ceiling the engine enforces, which '
      '$2 did not', pct < Decimal('5'))
check('...and it is charged to the user, as one line the quote can show',
      [c.kind for c in r.cost_lines()] == ['bridge_fee']
      and r.cost_lines()[0].payer == 'user')


# ── the provider's own gas figure ────────────────────────────────────────
check('the live response gives gasCosts as an object with totalNetworkFee in '
      'wei, not a list', isinstance(r.gas_costs_raw, dict)
      and r.gas_costs_raw.get('totalNetworkFee') == '1231589838153')
check('...and the gas limit and price are there too, so the estimate is the '
      'provider\'s own rather than this repository\'s guess',
      r.gas_costs_raw.get('gasLimit') == '148484'
      and r.gas_costs_raw.get('gasPrice') == '8204025')


# ── the fixture is for PARSING, never for signing ────────────────────────
# The calldata is complete and real this time, which makes it MORE useful and
# no more executable: it is one account's quote, long expired, and nothing in
# this repository signs from a fixture.
check('the capture carries the amount it was taken at, so a fixture can never '
      'be silently read as a different trade size',
      Decimal(str(fx['amount_usd'])) == Decimal('30'))


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
