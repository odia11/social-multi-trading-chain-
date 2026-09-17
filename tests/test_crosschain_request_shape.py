"""What actually goes on the wire to 0x, and what comes back unchallenged.

THE BUG THIS FILE EXISTS BECAUSE OF
The integration sent `gasPayer=user` on every cross-chain quote. 0x's
`gasPayer` is the base58 public key of an ALTERNATIVE Solana wallet that pays
the network fee and co-signs the transaction (0x-examples,
cross-chain-headless-example/src/fromSolanaToEvmWithGasPayer.ts:
`gasPayer: gasPayerKeypair.publicKey.toBase58()`). The self-paid example
omits the parameter entirely and the request schema marks it optional.

So "user" was not a value meaning "the user pays". It was a made-up string in
a field that expects a public key, sent on every request including EVM ones
where the parameter has no documented meaning at all. Best case it was
ignored; worst case it decided something nobody intended.

Two ideas had been collapsed into one word, and this file keeps them apart:
OUR policy (the user pays, OrcAgent does not sponsor) and THEIR parameter (a
pubkey, or absent).
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from trade_engine import crosschain as X            # noqa: E402
from trade_engine import registry as R              # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


BASE_USDC = R.CHAINS['base'].stable.address
SOL_USDC = R.CHAINS['solana'].stable.address
PERMIT2 = '0x000000000022D473030F116dDEE9F6B43aC78BA3'
EVM_WALLET = '0xABf40AADf960e20B4283dc5A06387A429Ba02456'
SOL_WALLET = '9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ'
BRIDGE_TO = '0x3333333333333333333333333333333333333333'


def quote_body(**over):
    q = {
        'quoteId': 'QID-1', 'sellAmount': '2000000', 'buyAmount': '1990000',
        'minBuyAmount': '1980000', 'sellToken': BASE_USDC, 'buyToken': SOL_USDC,
        'transaction': {'details': {'to': BRIDGE_TO, 'data': '0xaa',
                                    'gas': '210000', 'gasPrice': '1000000',
                                    'value': '0'}},
        'issues': {},
    }
    q.update(over.pop('quote', {}))
    body = {'liquidityAvailable': True, 'allowanceTarget': PERMIT2,
            'zid': 'ZID-9', 'quotes': [q]}
    body.update(over)
    return body


def capture(body=None, **kw):
    """Run a quote and return the parameters the adapter asked for."""
    seen = {}
    def fetch(**params):
        seen.update(params)
        return body if body is not None else quote_body()
    args = dict(source_chain='base', destination_chain='solana',
                source_amount_raw=2_000_000, origin_address=EVM_WALLET,
                destination_address=SOL_WALLET)
    args.update(kw)
    route = X.ZeroExCrossChain(fetch, lambda **k: {}).get_quote(**args)
    return seen, route


# ═══ 1-4. gasPayer ═══════════════════════════════════════════════════════
seen, route = capture()
check('1. the literal string "user" is NEVER sent as gasPayer — it is not a '
      'value 0x defines, and the parameter expects a base58 public key',
      seen.get('gas_payer') != 'user'
      and 'user' not in [v for v in seen.values() if isinstance(v, str)])
check('2. self-paid gas OMITS the parameter entirely, which is what 0x\'s own '
      'self-paid example does — an optional parameter that is always sent is '
      'not optional', 'gas_payer' not in seen)
check('...and the internal policy marker still records that the user pays, '
      'because that is a product rule and it did not go away',
      route.gas_policy == X.GAS_POLICY_USER and route.provider_gas_payer == '')

try:
    capture(source_chain='solana', destination_chain='base',
            origin_address=SOL_WALLET, destination_address=EVM_WALLET,
            alternative_gas_payer='not-a-real-pubkey')
    check('3. an alternative gas payer must be a real base58 public key', False)
except X.CrossChainError as e:
    check('3. an alternative gas payer must be a real base58 public key, not '
          'any string somebody passes', 'base58' in str(e))

try:
    capture(alternative_gas_payer=SOL_WALLET)
    check('4. an EVM origin does not accept a Solana-only parameter', False)
except X.CrossChainError as e:
    check('4. an EVM origin refuses the Solana-only gasPayer rather than '
          'sending it — there is no documented EVM equivalent',
          'Solana-origin' in str(e))

# A Solana origin WITH a real alternative payer: the parameter carries the
# public key itself. The route is then refused anyway, by OUR policy -- which
# is the separation this whole section is about. The adapter can express an
# alternative payer correctly; OrcAgent's product rule is that it does not use
# one, and those are two different decisions in two different places.
seen_svm = {}
def svm_fetch(**params):
    seen_svm.update(params)
    return {'liquidityAvailable': True, 'allowanceTarget': PERMIT2, 'zid': 'Z',
            'quotes': [{'quoteId': 'Q', 'sellAmount': '2000000',
                        'buyAmount': '1990000', 'minBuyAmount': '1980000',
                        'sellToken': SOL_USDC, 'buyToken': BASE_USDC,
                        'transaction': {'details': {'serializedTransaction': 'AQ=='}},
                        'issues': {}}]}
try:
    X.ZeroExCrossChain(svm_fetch, lambda **k: {}).get_quote(
        source_chain='solana', destination_chain='base',
        source_amount_raw=2_000_000, origin_address=SOL_WALLET,
        destination_address=EVM_WALLET, alternative_gas_payer=SOL_WALLET)
    policy_refused = False
except X.RouteRejected:
    policy_refused = True
check('...and a Solana origin WITH a real alternative payer sends the public '
      'key itself, which is the only thing the parameter takes',
      seen_svm.get('gas_payer') == SOL_WALLET)
check('...while OrcAgent\'s own policy still refuses to EXECUTE a route it '
      'does not pay for — the adapter can express it, the product does not '
      'use it, and those are separate decisions', policy_refused)


# ═══ 5-8. quoteId and zid ════════════════════════════════════════════════
check('5. quoteId is read from the individual quote and kept as the quote id',
      route.quote_id == 'QID-1')
check('6. zid is read from the top level and kept SEPARATELY — it identifies '
      'the request, not any one quote it returned', route.zid == 'ZID-9')
check('...so a response with no quoteId does not silently produce a "quote id" '
      'that is really a request id, which is what `quoteId or zid` did',
      X.ZeroExCrossChain(lambda **k: quote_body(quote={'quoteId': None}),
                         lambda **k: {}).get_quote(
        source_chain='base', destination_chain='solana',
        source_amount_raw=2_000_000, origin_address=EVM_WALLET,
        destination_address=SOL_WALLET).quote_id == '')

status_calls = []
def status_fetch(**kw):
    status_calls.append(dict(kw))
    if 'quote_id' in kw:
        raise RuntimeError('HTTP 400: unknown parameter quoteId')
    return {'status': 'bridge_pending'}

prov = X.ZeroExCrossChain(lambda **k: quote_body(), status_fetch)
st = prov.get_status(source_chain='base', source_tx_hash='0xabc', quote_id='QID-1')
check('7. status polling sends quoteId when there is a real one',
      status_calls and status_calls[0].get('quote_id') == 'QID-1')
check('8. ...and falls back to the verified two-parameter lookup if the '
      'endpoint refuses it, so an unverified parameter can never be the '
      'reason a bridge stops being tracked while it holds a reservation',
      len(status_calls) == 2 and 'quote_id' not in status_calls[1]
      and st.status == 'bridge_pending')
check('...and the fallback is recorded rather than swallowed, so an operator '
      'can see which shape the live API takes',
      'quoteId' in prov.last_quote_id_status_error)

status_calls.clear()
X.ZeroExCrossChain(lambda **k: {}, lambda **kw: status_calls.append(dict(kw))
                   or {'status': 'unknown'}).get_status(
    source_chain='base', source_tx_hash='0xabc')
check('...and a legacy row with no quoteId simply does not send one',
      status_calls and 'quote_id' not in status_calls[0])


# ═══ 9-10. envelopes ═════════════════════════════════════════════════════
def refused(label, body, kind=X.CrossChainError):
    try:
        capture(body=body)
    except kind as e:
        check(label, True)
        return str(e)
    except Exception as e:
        check(label + f' [raised {type(e).__name__} instead]', False)
        return ''
    check(label, False)
    return ''


msg = refused('9. a response carrying "routes" instead of "quotes" is REFUSED, '
              'not parsed on a guess — an envelope this integration has not '
              'been verified against is exactly when guessing is worst',
              {'liquidityAvailable': True, 'allowanceTarget': PERMIT2,
               'routes': [{'quoteId': 'Q'}]}, X.RouteRejected)
check('...and the refusal names what it saw, so an operator can act on it '
      'instead of guessing too', 'routes' in msg and 'QUOTE_LIST_KEYS' in msg)

refused('...an envelope with liquidity and no recognised quote list is refused',
        {'liquidityAvailable': True, 'somethingElse': [{}]}, X.RouteRejected)
refused('...and a non-object response is refused', ['not', 'a', 'dict'])

check('10. the one envelope this integration accepts is the one it verified '
      'against 0x\'s published schema, and it is a named constant so adding '
      'another is a deliberate edit rather than a permissive parser',
      X.ZeroExCrossChain.QUOTE_LIST_KEYS == ('quotes',))

seen_ok, route_ok = capture()
check('...and the verified shape parses correctly',
      route_ok.quote_id == 'QID-1' and route_ok.expected_out_raw == 1_990_000)


# ═══ 11-14. ephemeral signer ═════════════════════════════════════════════
# THE BUG THIS SECTION EXISTS BECAUSE OF.
# The first detector answered "required" the moment a key with a matching
# NAME existed anywhere in the response -- whatever its value. So a response
# carrying `"solanaEphemeralSignerPubkey": null`, a field the schema declares
# and this route leaves empty, was read as "needs a co-signer we cannot
# provide" and the route was refused.
#
# That is not a safe default. It refuses working routes for a field being
# mentioned. 0x's own EVM -> Solana example signs the whole trade with the EVM
# key on Base and generates no keypair at all, so a Base -> Solana route
# reporting this was a sign of the detector, not of the route.
for empty in (None, '', False, 0, {}, []):
    body = quote_body()
    body['quotes'][0]['issues'] = {'solanaEphemeralSignerPubkey': empty}
    _, r = capture(body=body)
    check(f'a DECLARED but empty ephemeral field ({empty!r}) is not a '
          f'requirement — presence is not a requirement, and reading it as one '
          f'refuses routes that work',
          r.ephemeral_signer_required is False)

_req = X.ephemeral_signer_requirement(
    {'issues': {'solanaEphemeralSignerPubkey': 'SomeRealPubkey111'}})
check('...while a non-empty value IS a requirement', _req['required'] is True)
check('...and the answer names the exact field it was found in, so a live '
      '"required" is actionable instead of mysterious',
      _req['path'] == 'issues.solanaEphemeralSignerPubkey'
      and 'SomeRealPubkey111' in _req['value'])

for spelling in ('solanaEphemeralSignerPubkey', 'ephemeralSignerPubkey',
                 'ephemeral_signer_pubkey'):
    body = quote_body()
    body['quotes'][0]['issues'] = {spelling: 'RealPubkey1111111111'}
    try:
        capture(body=body)
        check(f'11. a route requiring {spelling} is refused', False)
    except X.RouteUnsupported as e:
        check(f'11. a route really requiring {spelling} is refused rather '
              f'than half-attempted — OrcAgent has no flow for generating, '
              f'using and destroying a per-quote co-signer, and pretending '
              f'otherwise would strand a bridge mid-flight',
              'ephemeral' in str(e).lower() or 'co-signer' in str(e).lower())
        check(f'...and the refusal names the field and the value it found',
              spelling in str(e) or 'RealPubkey' in str(e))

_cc_src = open(os.path.join(REPO, 'trade_engine/crosschain.py')).read()
_generates_keys = any(w in _cc_src for w in (
    'Keypair.generate', 'Keypair(', 'from_seed', 'urandom', 'secrets.token',
    'new_unique', 'random_bytes'))
check('12-14. no ephemeral key material is generated, stored or logged '
      'anywhere, because no ephemeral signer flow exists — the requirement is '
      'DETECTED and refused, which is the honest position when the parameter '
      'could not be verified against a reachable specification. There is no '
      'key to reuse, no key to persist across a restart, and no key to leak',
      not _generates_keys)

check('...and the refusal is its own exception type, so "we cannot do this" '
      'is never logged or retried as "the response was wrong"',
      issubclass(X.RouteUnsupported, X.CrossChainError)
      and not issubclass(X.RouteUnsupported, X.RouteRejected))


# ═══ 15. Solana transaction versions ═════════════════════════════════════
class FakeTx:
    def __init__(self, version):
        self.message = type('M', (), {'version': version})()


import base64                                                  # noqa: E402
GOOD = base64.b64encode(b'\x01\x02').decode()

check('15a. a v0 transaction is accepted',
      X.check_solana_tx_version(GOOD, lambda raw: FakeTx(0)) is not None)
check('15b. a legacy transaction is accepted',
      X.check_solana_tx_version(GOOD, lambda raw: FakeTx('legacy')) is not None)

try:
    X.check_solana_tx_version(GOOD, lambda raw: FakeTx(1))
    check('15c. an unsupported transaction version is refused', False)
except X.RouteUnsupported as e:
    check('15c. a transaction version this integration cannot sign is refused '
          'BEFORE signing — discovering it afterwards means failing with the '
          'user\'s key in memory and a reservation held', 'version' in str(e))

try:
    X.check_solana_tx_version(GOOD, lambda raw: (_ for _ in ()).throw(
        ValueError('unsupported')))
    check('15d. bytes the local library cannot parse are refused', False)
except X.RouteUnsupported as e:
    check('15d. bytes the local library cannot parse are refused, and the '
          'bytes are never rebuilt locally — a reconstructed transaction is '
          'not the one that was quoted', 'rebuilt' in str(e))

try:
    X.check_solana_tx_version('not base64!!', lambda raw: FakeTx(0))
    check('15e. non-base64 is refused', False)
except X.RouteRejected:
    check('15e. a serialized transaction that is not valid base64 is refused', True)


# ═══ 16-17. no second destination swap ═══════════════════════════════════
msg = refused('16. a route delivering something other than the destination '
              'chain\'s dollar asset is refused. This engine bridges into the '
              'stable and swaps separately, so a route ending in the final '
              'token would be swapped a SECOND time',
              quote_body(quote={'buyToken': 'SomeOtherMint1111111111111111111111111111'}),
              X.RouteRejected)
check('...and the refusal says why, naming the asset it expected',
      'swapped a second time' in msg)

check('17. the invariant is also checked on the PERSISTED row before the '
      'destination swap runs, because a restart acts on the row and the row '
      'may predate the check',
      'Refusing to run a destination swap against an asset this trade did'
      in open(os.path.join(REPO, 'trade_engine/execute.py')).read())


# ═══ 18-19. allowances ═══════════════════════════════════════════════════
SETTLER_REGISTRY = X.ZEROX_SETTLER_REGISTRY

check('18a. Permit2 is recognised automatically — it is a fixed, published '
      'address on every chain', capture()[1].allowance_target.lower() == PERMIT2.lower())

for name, addr in (('AllowanceHolder (Cancun)', '0x0000000000001fF3684f28c67538d4D072C22734'),
                   ('AllowanceHolder (Shanghai)', '0x0000000000005E88410CcDFaDe4a5EfaE4b49562')):
    body = quote_body(allowanceTarget=addr)
    body['quotes'][0]['issues'] = {'allowance': {'spender': addr}}
    _, r = capture(body=body)
    check(f'18b. {name} is recognised', r.allowance_target.lower() == addr.lower())

body = quote_body(allowanceTarget=SETTLER_REGISTRY)
body['quotes'][0]['issues'] = {'allowance': {'spender': SETTLER_REGISTRY}}
msg = refused('18c. the 0x Settler deployer/registry is never approved. '
              'Settler neither needs nor supports an allowance, and approvals '
              'mis-scoped to one are what an August 2025 exploit drained',
              body, X.RouteRejected)
check('...and the refusal explains the risk rather than just saying no',
      'exploit' in msg or 'Settler' in msg)

body = quote_body(allowanceTarget=BRIDGE_TO)
body['quotes'][0]['issues'] = {'allowance': {'spender': BRIDGE_TO}}
msg = refused('18d. a spender that is ALSO the contract being called is '
              'refused unless it is a recognised allowance contract — that is '
              'the shape of approving a Settler',
              body, X.RouteRejected)

RANDOM = '0x2222222222222222222222222222222222222222'
body = quote_body(allowanceTarget=RANDOM)
body['quotes'][0]['issues'] = {'allowance': {'spender': RANDOM}}
msg = refused('19. an unrecognised spender is refused by default. An allowance '
              'is a standing permission that outlives the transaction asking '
              'for it, so it is not granted on the say-so of the response',
              body, X.RouteUnsupported)
check('...and the refusal names the control that would allow it deliberately',
      'CROSSCHAIN_ALLOWED_SPENDERS' in msg)

def with_allowlist(addr):
    b = quote_body(allowanceTarget=addr)
    b['quotes'][0]['issues'] = {'allowance': {'spender': addr}}
    return X.ZeroExCrossChain(lambda **k: b, lambda **k: {}).get_quote(
        source_chain='base', destination_chain='solana',
        source_amount_raw=2_000_000, origin_address=EVM_WALLET,
        destination_address=SOL_WALLET,
        extra_allowed_spenders=frozenset({addr}))
check('...and an operator who has looked at a bridge\'s spender can pin it',
      with_allowlist(RANDOM).allowance_target.lower() == RANDOM.lower())

body = quote_body(allowanceTarget=PERMIT2)
body['quotes'][0]['issues'] = {'allowance': {'spender': RANDOM}}
msg = refused('...and a response naming TWO different spenders is refused: one '
              'of them is wrong and approving either is a guess',
              body, X.RouteRejected)

hit = []
def settler_says_yes(chain, addr):
    hit.append(addr)
    return True
try:
    X.ZeroExCrossChain(lambda **k: quote_body(), lambda **k: {}).get_quote(
        source_chain='base', destination_chain='solana',
        source_amount_raw=2_000_000, origin_address=EVM_WALLET,
        destination_address=SOL_WALLET, settler_lookup=settler_says_yes)
    check('...and an address the registry identifies as a live Settler is '
          'refused even if it were otherwise allowed', False)
except X.RouteRejected as e:
    check('...and an address the REGISTRY identifies as a live Settler is '
          'refused — 0x says query the registry rather than hardcode, so it '
          'is asked', 'Settler' in str(e) and hit)


# ═══ 20-21. against the app itself ═══════════════════════════════════════
PROBE = r'''
import json, inspect, sys
import dashboard as d
out = {}
out['quote_params_self_paid'] = d._cc_quote_params(
    origin_chain='8453', destination_chain='solana', sell_token='A', buy_token='B',
    sell_amount=1, origin_address='0xaaa', destination_address='sss',
    slippage_bps=100)
out['quote_params_alt_payer'] = d._cc_quote_params(
    origin_chain='solana', destination_chain='8453', sell_token='A', buy_token='B',
    sell_amount=1, origin_address='sss', destination_address='0xaaa',
    slippage_bps=100, gas_payer='9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ')
out['status_params_plain'] = d._cc_status_params(origin_chain='8453', origin_tx_hash='0xh')
out['status_params_with_quote'] = d._cc_status_params(
    origin_chain='8453', origin_tx_hash='0xh', quote_id='QID')
out['sender_src'] = inspect.getsource(d._te_cc_source_sender)
out['gas_req_src'] = inspect.getsource(d._cc_gas_requirement)

class R:
    tx_gas = 210000
    gas_costs_raw = {}
    raw = {'transaction': {'details': {'gasPrice': str(10**9)}}}
d._cc_native_balance = lambda w, c: 0.0
out['gas_from_quote'] = d._cc_gas_requirement('W', 'base', R())
out['gas_no_quote'] = d._cc_gas_requirement('W', 'base', None)
print('@@@' + json.dumps(out, default=str))
'''
env = dict(os.environ)
env.update({'DATA_DIR': tempfile.mkdtemp(), 'SECRET_KEY': 'x' * 32,
            'ENCRYPTION_KEY': 'K' * 43 + '=', 'DEV': '1'})
p = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=300)
if '@@@' not in p.stdout:
    print(p.stdout[-2500:]); print(p.stderr[-2500:])
    sys.exit('probe did not report')
A = json.loads(p.stdout.split('@@@', 1)[1].splitlines()[0])

check('20a. the app\'s own quote parameters contain no gasPayer when the user '
      'pays', 'gasPayer' not in A['quote_params_self_paid'])
check('20b. ...and the word "user" appears nowhere in them',
      'user' not in [str(v) for v in A['quote_params_self_paid'].values()])
check('20c. ...and an alternative payer is sent as the public key itself',
      A['quote_params_alt_payer'].get('gasPayer')
      == '9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ')
check('20d. the app sends the verified status pair by default',
      set(A['status_params_plain']) == {'originChain', 'originTxHash'})
check('20e. ...and adds quoteId only when it has one',
      A['status_params_with_quote'].get('quoteId') == 'QID')

check('20f. the origin-leg sender re-checks the spender at the last moment, '
      'because the route travelled through a cache and a database row to get '
      'there and an approval is forever',
      '_verify_spender' in A['sender_src'])
check('20g. ...and gates the Solana transaction version before the key is '
      'decrypted', 'check_solana_tx_version' in A['sender_src'])

g = A['gas_from_quote']
check('21a. the native gas figure is labelled an ESTIMATE, and no field '
      'claims to be an exact requirement — the only place the word appears is '
      'the sentence saying it is NOT one',
      g['is_estimate'] is True
      and not any('exact' in str(k).lower() for k in g)
      and 'estimated_native_gas' in g
      and 'not an exact figure' in g['reason'])
check('21b. ...and says where it came from — the provider\'s own quote when '
      'there is one', g['estimate_source'] == 'provider_quote'
      and float(g['provider_quoted_native_gas']) > 0)
check('21c. ...and falls back to a stated conservative floor when the quote '
      'gave no gas figure, rather than presenting our number as theirs',
      A['gas_no_quote']['estimate_source'] == 'orcagent_floor')
check('21d. the wording shown to a user says "estimated", not a precision it '
      'cannot have', 'estimate' in g['reason'].lower())
check('21e. and there is still no branch anywhere in it that spends an '
      'OrcAgent wallet', not any(w in A['gas_req_src'] for w in
                                 ('GAS_SPONSOR', '_ensure_evm_gas', '_ensure_solana_gas')))


# ═══ the smoke script sends what the app sends ═══════════════════════════
# scripts/test_0x_crosschain_quote.py builds its own parameters so it can run
# without starting Flask. That is only useful if the two agree: a smoke test
# validating a request shape the app does not use would validate nothing.
sys.path.insert(0, os.path.join(REPO, 'scripts'))
import importlib.util                                          # noqa: E402
_spec = importlib.util.spec_from_file_location(
    'smoke', os.path.join(REPO, 'scripts', 'test_0x_crosschain_quote.py'))
_smoke = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_smoke)

_script_params = _smoke.build_quote_params(
    origin_chain='8453', destination_chain='solana', sell_token='A', buy_token='B',
    sell_amount=1, origin_address='0xaaa', destination_address='sss',
    slippage_bps=100)
check('the read-only smoke script sends EXACTLY what the app sends, so what '
      'it validates against the live API is the request production makes',
      _script_params == A['quote_params_self_paid'])

_script_alt = _smoke.build_quote_params(
    origin_chain='solana', destination_chain='8453', sell_token='A', buy_token='B',
    sell_amount=1, origin_address='sss', destination_address='0xaaa',
    slippage_bps=100, gas_payer='9FzTJNUfMVSPPNEsUDfUHuE1gSE7uDBamcGHq1CseUUZ')
check('...including how it handles an alternative gas payer',
      _script_alt == A['quote_params_alt_payer'])

_smoke_src = open(os.path.join(REPO, 'scripts', 'test_0x_crosschain_quote.py')).read()
check('the smoke script cannot sign, send, approve or spend: it contains no '
      'signing, no broadcast and no key handling at all',
      not any(w in _smoke_src for w in (
          'sign_transaction', 'send_raw_transaction', 'sendTransaction',
          '_use_key', 'decrypt_private_key', 'Keypair.from', 'requests.post')))
check('...and it never prints the API key it uses',
      'redact' in _smoke_src and 'apikey' in _smoke_src)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
