"""The cross-chain adapter, and the responses it has to refuse.

WHY THIS FILE IS MOSTLY ABOUT REFUSING THINGS
A cross-chain quote is not data. It is a contract address to approve, a
contract to call, and calldata to send it -- everything an attacker would
need, arriving over HTTP from outside the process. If the endpoint were ever
compromised, or a response ever forged in transit, verify_route() is the only
thing standing between that response and the user's balance.

So the tests below are not "does it parse". They are: here is a response that
is subtly wrong in one specific way, does it get through. Each one is a real
way money leaves.

The field names come from 0x's own published example
(0xProject/0x-examples, cross-chain-headless-example/src/schemas.ts), read
directly because api.0x.org and docs.0x.org are both unreachable from the
build environment.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trade_engine import crosschain as X            # noqa: E402
from trade_engine import registry as R              # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


BASE_USDC = R.CHAINS['base'].stable.address          # 6 decimals
SOL_USDC = R.CHAINS['solana'].stable.address         # 6 decimals
BSC_USDC = R.CHAINS['bsc'].stable.address            # 18 decimals
EVM_WALLET = '0x1111111111111111111111111111111111111111'
SOL_WALLET = '9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ'
SPENDER = '0x2222222222222222222222222222222222222222'
BRIDGE_TO = '0x3333333333333333333333333333333333333333'

SEND = 100_000_000          # 100 USDC at 6 decimals
GET = 99_500_000            # 99.50 out
MIN = 99_000_000            # 99.00 guaranteed


def response(**over):
    """A well-formed Base -> Solana quote, with named fields overridden."""
    quote = {
        'quoteId': 'route-abc',
        'sellAmount': str(SEND),
        'buyAmount': str(GET),
        'minBuyAmount': str(MIN),
        'estimatedTimeSeconds': 45,
        'originAddress': EVM_WALLET,
        'destinationAddress': SOL_WALLET,
        'fees': {'zeroExFee': {'amount': '100000', 'token': BASE_USDC}},
        'steps': [{'type': 'bridge', 'provider': 'cctp'}],
        'transaction': {'details': {'to': BRIDGE_TO, 'data': '0xdeadbeef',
                                    'gas': '210000', 'gasPrice': '1000000',
                                    'value': '0'}},
        'issues': {},
    }
    quote.update(over.pop('quote', {}))
    body = {'liquidityAvailable': True, 'allowanceTarget': SPENDER,
            'zid': 'zid-1', 'quotes': [quote]}
    body.update(over)
    return body


def provider(body, status_body=None):
    return X.ZeroExCrossChain(lambda **kw: body, lambda **kw: status_body or {})


def get(body, **kw):
    args = dict(source_chain='base', destination_chain='solana',
                source_amount_raw=SEND, origin_address=EVM_WALLET,
                destination_address=SOL_WALLET)
    args.update(kw)
    return provider(body).get_quote(**args)


# ── chain identifiers ────────────────────────────────────────────────────
check('an EVM chain is identified to the provider by its numeric chain id',
      X.chain_param('base') == '8453' and X.chain_param('bsc') == '56')
check('Solana goes as the literal string, not as a number — the numeric '
      '999999999991 appears only in STATUS responses and sending it on a '
      'quote is how a route reads as "not found" forever',
      X.chain_param('solana') == 'solana')


# ── the happy path ───────────────────────────────────────────────────────
route = get(response())
check('a well-formed quote is accepted', route.route_id == 'route-abc')
check('...and carries the spender that would be approved',
      route.allowance_target == SPENDER)
check('...and the call target, which is not the same thing',
      route.tx_to == BRIDGE_TO and route.tx_to != route.allowance_target)
check('...and both tokens, resolved from the registry rather than from the '
      'response', route.source_token == BASE_USDC and route.destination_token == SOL_USDC)
check('the bridge cost is what goes in minus what is GUARANTEED out, not a '
      'sum of the provider\'s fee objects — those are in several different '
      'tokens and adding them means inventing exchange rates',
      str(route.loss_usd()) == '1.00')
check('...and it becomes one cost line the engine can price against the ceiling',
      [c.kind for c in route.cost_lines()] == ['bridge_fee']
      and route.cost_lines()[0].payer == 'user')


# ── responses that must be refused ───────────────────────────────────────
def rejected(label, body, **kw):
    try:
        get(body, **kw)
    except X.RouteRejected:
        check(label, True)
        return
    except X.CrossChainError as e:
        check(label + ' [rejected as unroutable rather than as invalid]', False)
        return
    check(label, False)


rejected('a route that would deliver to somebody else\'s wallet is refused — '
         'this is the theft the rest of the checks exist to make boring',
         response(quotes=[dict(response()['quotes'][0],
                               destinationAddress='9xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')]))

rejected('a route that would send from an address the user does not control '
         'is refused',
         response(quotes=[dict(response()['quotes'][0],
                               originAddress='0x9999999999999999999999999999999999999999')]))

rejected('a route that re-sized the trade is refused — the ceiling was '
         'computed against OUR number, so spending theirs breaks it',
         response(quotes=[dict(response()['quotes'][0], sellAmount=str(SEND * 2))]))

rejected('a route that guarantees more than it expects to deliver is refused: '
         'that is not a guarantee, it is an inconsistent response',
         response(quotes=[dict(response()['quotes'][0], minBuyAmount=str(GET + 1))]))

rejected('a route claiming to deliver MORE dollars than it takes in is refused '
         'rather than believed — the surplus would flow straight into the '
         'user\'s quoted output',
         response(quotes=[dict(response()['quotes'][0],
                               buyAmount=str(SEND * 2), minBuyAmount=str(SEND * 2))]))

rejected('a route whose call target is the USDC contract itself is refused — '
         'that is a token transfer wearing a bridge\'s name, and the calldata '
         'decides where the money goes',
         response(quotes=[dict(response()['quotes'][0],
                               transaction={'details': {'to': BASE_USDC,
                                                        'data': '0xa9059cbb',
                                                        'gas': '60000', 'value': '0'}})]))

rejected('a route naming an unusable spender is refused before anything is '
         'approved',
         response(allowanceTarget='not-an-address'))

rejected('a route with no usable call target is refused',
         response(quotes=[dict(response()['quotes'][0],
                               transaction={'details': {'data': '0xabc'}})]))

rejected('a route with a zero sell amount is refused',
         response(quotes=[dict(response()['quotes'][0], buyAmount='0')]))

rejected('a route that would have somebody other than the user pay the gas is '
         'refused — this engine executes nothing it does not charge for',
         response(), gas_payer='orcagent')


# ── fake USDC ────────────────────────────────────────────────────────────
# The registry is keyed on (chain, address), so there is no code path where a
# token merely CALLED USDC can be substituted. This proves the adapter reads
# the address from the registry rather than echoing the response.
fake = dict(response())
fake['quotes'] = [dict(response()['quotes'][0], buyToken='FakeUSDCMint111111111111111111111111111111')]
route = get(fake)
check('a buyToken the response made up cannot become the destination asset: '
      'the adapter takes both tokens from the registry, by address, so a '
      'scam token named USDC has nothing to substitute itself into',
      route.destination_token == SOL_USDC)


# ── no route at all is not the same as a bad route ───────────────────────
try:
    get({'liquidityAvailable': False})
    check('no liquidity is reported as no route', False)
except X.RouteRejected:
    check('no liquidity is reported as NO ROUTE, not as an invalid response — '
          'they must never be logged, counted or retried as the same thing', False)
except X.CrossChainError:
    check('no liquidity is reported as NO ROUTE, not as an invalid response — '
          'they must never be logged, counted or retried as the same thing', True)

try:
    provider(response()).get_quote(
        source_chain='base', destination_chain='base', source_amount_raw=SEND,
        origin_address=EVM_WALLET, destination_address=EVM_WALLET)
    check('asking for a cross-chain quote on one chain is refused', False)
except X.CrossChainError:
    check('asking for a cross-chain quote on a single chain is refused — the '
          'caller should have taken the direct route, and pricing a bridge it '
          'will not use would overcharge the ceiling', True)


# ── decimals across chains ───────────────────────────────────────────────
# BSC's USDC has 18 decimals and Base's has 6. A bridge cost computed without
# noticing that is wrong by a factor of 10^12.
bsc_route = X.ZeroExCrossChain(
    lambda **kw: {'liquidityAvailable': True, 'allowanceTarget': SPENDER,
                  'quotes': [{'quoteId': 'r2',
                              'sellAmount': str(100 * 10**18),
                              'buyAmount': str(99_500_000),
                              'minBuyAmount': str(99_000_000),
                              'transaction': {'details': {'to': BRIDGE_TO,
                                                          'data': '0x01', 'value': '0'}},
                              'issues': {}}]},
    lambda **kw: {}).get_quote(
        source_chain='bsc', destination_chain='base',
        source_amount_raw=100 * 10**18, origin_address=EVM_WALLET,
        destination_address=EVM_WALLET)
check('a BSC -> Base bridge prices its cost across DIFFERENT decimals (18 in, '
      '6 out) and still gets $1.00 — comparing the raw integers would be off '
      'by a factor of a trillion', str(bsc_route.loss_usd()) == '1.00')


# ── status ───────────────────────────────────────────────────────────────
def status(body):
    return provider(response(), body).get_status(source_chain='base',
                                                 source_tx_hash='0xsrc')


st = status({'status': 'bridge_filled',
             'transactions': [{'txHash': '0xsrc'}, {'txHash': 'DESTSIG'}],
             'steps': [{'type': 'bridge', 'settledBuyAmount': '99400000'}]})
check('a filled bridge is reported filled', st.filled and not st.failed)
check('...with the destination transaction, picked as the one that is not the '
      'origin', st.destination_tx_hash == 'DESTSIG')
check('...and the amount that ACTUALLY settled, which is what reconciliation '
      'needs and is not the same as the quote', st.settled_out_raw == 99_400_000)

st = status({'status': 'bridge_pending'})
check('a pending bridge is neither filled nor failed, and says the origin is '
      'already on chain — so it must never be retried',
      not st.filled and not st.failed and st.source_on_chain)

st = status({'status': 'origin_tx_reverted'})
check('a reverted origin transaction is a failure where nothing left the '
      'source chain', st.failed and not st.filled)

st = status({'status': 'bridge_failed',
             'failure': {'reason': 'no fill', 'recovery': {'refundTxHash': '0xr'}}})
check('a failed bridge carries its reason and its recovery information — the '
      'money is somewhere and that is what says where',
      st.failed and st.failure_reason == 'no fill'
      and st.recovery.get('refundTxHash') == '0xr')

st = status({'status': 'something_0x_added_last_tuesday'})
check('a status nobody recognises reads as unknown and keeps the trade where '
      'it is — guessing it means "filled" is how a bridge gets declared done '
      'while the money is still in flight',
      st.status == X.UNKNOWN and not st.filled and not st.failed)

st = status({})
check('a status response with no status at all is unknown, not filled',
      st.status == X.UNKNOWN and not st.filled)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
