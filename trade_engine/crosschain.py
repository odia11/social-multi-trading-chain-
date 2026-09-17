"""Moving USDC between chains, normalised into something the engine can hold.

WHY THIS EXISTS SEPARATELY FROM providers.py
providers.py normalises a SWAP: one chain, one transaction, an answer in
seconds. A bridge is none of those things. It is two transactions on two
chains with minutes of nothing in between, and the only honest way to model
it is as a thing that is started, persisted, and later asked about. So the
adapter here has a status side that a swap provider has no use for, and the
engine drives it from a worker rather than from a request.

WHERE THE FIELD NAMES COME FROM
docs.0x.org and api.0x.org are unreachable from this environment (the egress
proxy answers 403 to CONNECT). The request/response shapes below were read
from 0x's own published example, 0xProject/0x-examples,
cross-chain-headless-example/src/schemas.ts and config.ts -- the Zod schemas
that example validates live responses against. That is a primary source and
it is current, but it is not the same as having exercised the live API, and
the repository's own history records a real "No bridge route found" that was
never root-caused. So every field is read defensively and every route is
verified before it can move money: a shape this does not recognise fails
closed, as "no route", never as a misread amount.

WHAT IS TREATED AS UNTRUSTED
All of it. A cross-chain quote arrives carrying a contract to approve, a
contract to call, and calldata to send it -- which is to say, it arrives
carrying everything an attacker would need if the response were ever forged
or the endpoint ever compromised. verify_route() below is what stands
between that response and the user's balance: the chains, both tokens, the
amount, the recipient and the spender are each checked against what WE asked
for and against the registry, and anything that does not match is refused
rather than repaired.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_UP
from typing import Callable, Optional

from . import registry as R
from .costs import CostLine, ZERO, KIND_BRIDGE_FEE


class CrossChainError(Exception):
    """A route could not be obtained or could not be trusted."""


class RouteRejected(CrossChainError):
    """The provider answered, and the answer did not survive validation.

    Deliberately distinct from "no route": one means nobody can do this
    trade, the other means somebody returned something wrong. They should
    never be logged, counted or retried as the same thing.
    """


class NoLiquidity(CrossChainError):
    """The provider answered, correctly, that it cannot serve this trade.

    Its own outcome, and deliberately not RouteRejected or RouteUnsupported.
    Nothing is wrong: not the response, not this integration, not the
    provider. There simply is no route at this size right now, which is a
    fact about a market and can change by the hour.

    Naming it matters because of what must NOT happen next. A quiet market is
    not a reason to invent a route, fall back to a hand-rolled bridge,
    substitute a different asset, or record the provider as broken. It is a
    reason to say so and stop.
    """
    code = 'NO_CROSSCHAIN_LIQUIDITY'

    def __init__(self, message, *, source_chain='', destination_chain='',
                 amount_raw=0, provider='', zid=''):
        super().__init__(message)
        self.source_chain = source_chain
        self.destination_chain = destination_chain
        self.amount_raw = amount_raw
        self.provider = provider
        self.zid = zid

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'message': str(self),
            'source_chain': self.source_chain,
            'destination_chain': self.destination_chain,
            'amount_raw': str(self.amount_raw),
            'provider': self.provider,
            # The provider's own handle for the request. It is the thing 0x
            # support would ask for, and it is the only identifier a
            # no-liquidity response carries -- there is no quoteId, because
            # there is no quote.
            'zid': self.zid,
        }


class RouteUnsupported(CrossChainError):
    """The route is real and we will not execute it.

    Not a rejection of the response and not an absence of liquidity: 0x
    offered something this integration cannot carry out safely -- an
    ephemeral co-signer it has no flow for, a transaction version its
    libraries cannot parse. Separate so it is obvious in a log that the
    limitation is ours.
    """


# ── gas: our policy, and their parameter ─────────────────────────────────
# These are two different things and conflating them is how the literal
# string 'user' ended up being sent to an API that expects a base58 public
# key.
#
# GAS_POLICY_USER is OUR marker. It means OrcAgent is not paying, which is a
# product rule and is never transmitted anywhere.
#
# The provider's `gasPayer` parameter is something else entirely: 0x's own
# example (0x-examples, cross-chain-headless-example/src/
# fromSolanaToEvmWithGasPayer.ts) passes
#
#     gasPayer: gasPayerKeypair.publicKey.toBase58()
#
# -- the base58 public key of an ALTERNATIVE Solana wallet that pays the fee
# and co-signs the transaction. The plain self-paid example
# (fromSolanaToEvm.ts) does not send the parameter at all, and the request
# schema marks it optional.
#
# So when the user pays their own gas the parameter is OMITTED. There is no
# documented value meaning "the user pays"; inventing one and sending it is
# either ignored or rejected, and neither is a thing to guess about.
GAS_POLICY_USER = 'user'
GAS_POLICY_ALTERNATIVE = 'alternative_payer'


# The provider's own status vocabulary, verified against schemas.ts.
# Anything outside this set is read as UNKNOWN rather than guessed into a
# terminal state -- a status 0x adds later must fail safe (keep polling),
# never unsafe (declare a bridge filled that is not).
ORIGIN_PENDING = 'origin_tx_pending'
ORIGIN_SUCCEEDED = 'origin_tx_succeeded'
ORIGIN_CONFIRMED = 'origin_tx_confirmed'
ORIGIN_REVERTED = 'origin_tx_reverted'
BRIDGE_PENDING = 'bridge_pending'
BRIDGE_FILLED = 'bridge_filled'
BRIDGE_FAILED = 'bridge_failed'
UNKNOWN = 'unknown'

ALL_STATUSES = frozenset({
    ORIGIN_PENDING, ORIGIN_SUCCEEDED, ORIGIN_CONFIRMED, ORIGIN_REVERTED,
    BRIDGE_PENDING, BRIDGE_FILLED, BRIDGE_FAILED, UNKNOWN,
})
TERMINAL_STATUSES = frozenset({BRIDGE_FILLED, BRIDGE_FAILED, ORIGIN_REVERTED})
# The origin leg is on chain and will not un-happen. Past this point a retry
# is a second bridge, not a retry.
SOURCE_IS_ON_CHAIN = frozenset({
    ORIGIN_SUCCEEDED, ORIGIN_CONFIRMED, BRIDGE_PENDING, BRIDGE_FILLED,
    BRIDGE_FAILED, ORIGIN_REVERTED,
})

_EVM_ADDRESS = re.compile(r'^0x[0-9a-fA-F]{40}$')
_SVM_ADDRESS = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')

# ── who may be given an ERC-20 allowance ─────────────────────────────────
# 0x is explicit: NEVER set an allowance on the Settler contract. It neither
# needs nor supports one, and approvals mis-scoped to a Settler are what an
# August 2025 exploit drained. The correct spender is the one the API returns
# through its allowance flow -- allowanceTarget, or issues.allowance.spender.
#
# Settler addresses deliberately CANNOT be deny-listed: 0x's own instruction
# is "do not hardcode any Settler address, always query the deployer/registry
# for the most recent one", so any list here would go stale and give false
# assurance. The defence is the other way round -- an ALLOWLIST of the
# contracts that legitimately hold allowances, which are fixed and published:
#
#   Permit2                          same address on every chain
#   AllowanceHolder (Cancun)         Ethereum, Base, Arbitrum, Polygon, ...
#   AllowanceHolder (Shanghai)       Mantle and other pre-Cancun chains
#
# A cross-chain route may legitimately nominate a bridge contract instead, so
# the allowlist is extensible by the operator -- see extra_allowed in
# verify_route. What it is not is open: an unrecognised spender is refused
# until somebody looks at it.
CANONICAL_ALLOWANCE_TARGETS = frozenset(a.lower() for a in (
    '0x000000000022D473030F116dDEE9F6B43aC78BA3',   # Permit2, all chains
    '0x0000000000001fF3684f28c67538d4D072C22734',   # AllowanceHolder, Cancun
    '0x0000000000005E88410CcDFaDe4a5EfaE4b49562',   # AllowanceHolder, Shanghai
))

# The Settler deployer/registry. Not a Settler itself, but approving it would
# be the same class of mistake, and unlike the Settlers it is a fixed address.
ZEROX_SETTLER_REGISTRY = '0x00000000000004533Fe15556B1E086BB1A72cEae'.lower()

# Solana transaction versions this integration can parse and sign. `solders`
# handles legacy and v0; anything else is refused BEFORE signing rather than
# being discovered as an opaque parse error at broadcast time.
SUPPORTED_SOLANA_TX_VERSIONS = ('legacy', 0)

# A Solana-origin route may require a freshly generated co-signer whose public
# key is handed to the provider at quote time and whose private key signs
# alongside the user's. OrcAgent has no flow for that -- generating,
# persisting and destroying per-quote key material is its own piece of work,
# and the parameter's exact name and signing order could not be verified
# against a reachable specification.
#
# So it is DETECTED and REFUSED rather than attempted. These are the key
# spellings that would indicate it; matching is on a normalised key so a
# response using a different case or separator is still caught.
_EPHEMERAL_HINTS = ('solanaephemeralsignerpubkey', 'ephemeralsignerpubkey',
                    'ephemeralsigner', 'ephemeralsignerpublickey')


def ephemeral_signer_requirement(*objects) -> dict:
    """Whether these response objects genuinely ask for a co-signer.

    Returns {'required': bool, 'path': str, 'value': repr, 'reason': str} so a
    caller can say WHY rather than only that. The path is what makes a live
    "required" answer actionable instead of mysterious.

    PRESENCE IS NOT A REQUIREMENT, AND THIS IS THE WHOLE POINT.
    The first version of this returned True the moment a key with a matching
    NAME existed anywhere in the response. A response carrying
    `"solanaEphemeralSignerPubkey": null` -- a field declared by the schema and
    left empty because this route does not use one -- was therefore read as
    "this route needs a co-signer we cannot provide", and the route was
    refused.

    That is not a safe default, it is a broken one: it refuses working routes
    for a field being mentioned. 0x's own EVM -> Solana example
    (0x-examples/cross-chain-headless-example/src/fromEvmToSolana.ts) signs
    the whole trade with the EVM key on Base and passes the Solana side as a
    destination address only -- no keypair is generated anywhere in it. So a
    Base -> Solana route reporting "ephemeral signer required" was a strong
    sign of this bug rather than of the route.

    A requirement now needs a MEANINGFUL value: a non-empty string, a true, a
    non-empty structure. Null, empty string, false and empty collections are
    the field being declared and not used.
    """
    EMPTY = (None, '', False, 0)

    def walk(node, path='', depth=0):
        if depth > 6:
            return None
        if isinstance(node, dict):
            for k, v in node.items():
                here = f'{path}.{k}' if path else str(k)
                flat = str(k).replace('_', '').replace('-', '').lower()
                if flat in _EPHEMERAL_HINTS:
                    if isinstance(v, (dict, list)):
                        if v:
                            return (here, v)
                    elif v not in EMPTY:
                        return (here, v)
                    # Declared and empty: this route does not use one.
                    continue
                found = walk(v, here, depth + 1)
                if found:
                    return found
        elif isinstance(node, list):
            for i, v in enumerate(node[:20]):
                found = walk(v, f'{path}[{i}]', depth + 1)
                if found:
                    return found
        return None

    for obj in objects:
        hit = walk(obj)
        if hit:
            path, value = hit
            return {
                'required': True, 'path': path,
                'value': repr(value)[:120],
                'reason': (f'the response carries a non-empty {path}, which is a '
                           f'co-signer this integration must provide'),
            }
    return {'required': False, 'path': '', 'value': '',
            'reason': 'no non-empty ephemeral-signer field in the response'}


def _needs_ephemeral_signer(*objects) -> bool:
    """Thin bool over ephemeral_signer_requirement(), for callers that only
    need the answer and not the reasoning."""
    return ephemeral_signer_requirement(*objects)['required']


def chain_param(chain: str) -> str:
    """The provider's identifier for a chain, on the REQUEST side.

    EVM chains go as their numeric chain id; Solana goes as the literal
    string 'solana' (config.ts: CHAIN_IDS.solana = "solana"). Note the status
    RESPONSE uses a different value for Solana -- 999999999991 -- which is
    only ever read, never sent. Mixing those two up is the sort of thing that
    reads as "no route" forever.
    """
    cfg = R.get_chain(chain)
    if cfg.kind == 'svm':
        return 'solana'
    if cfg.chain_id is None:
        raise CrossChainError(f'{chain} has no chain id to send')
    return str(cfg.chain_id)


def _positive_int(value, what: str) -> int:
    try:
        n = int(str(value))
    except (TypeError, ValueError):
        raise RouteRejected(f'{what} is not a number: {value!r}')
    if n <= 0:
        raise RouteRejected(f'{what} must be positive, got {n}')
    return n


def _same_address(a: str, b: str) -> bool:
    return (a or '').strip().lower() == (b or '').strip().lower()


def _valid_address(chain: str, address: str) -> bool:
    kind = R.get_chain(chain).kind
    pattern = _SVM_ADDRESS if kind == 'svm' else _EVM_ADDRESS
    return bool(pattern.match((address or '').strip()))


@dataclass(frozen=True)
class CrossChainRoute:
    """One priced way to move USDC from one chain to another.

    Everything the engine needs to execute it, decide against it, or pick it
    up again tomorrow. Amounts are raw integers in their own token's units --
    never floats, and never converted to USD here, because a bridge quote
    prices in tokens and inventing a dollar figure is how a fee gets counted
    twice.
    """
    provider: str
    # ── two identifiers, two meanings, never interchanged ──
    # quote_id is 0x's `quoteId`, which lives on an individual quote inside
    # the `quotes` array. zid is the top-level `zid` on the response, which
    # identifies the REQUEST rather than any one quote it returned.
    #
    # They were previously collapsed into a single route_id with
    # `quoteId or zid`, so a response that happened to omit quoteId silently
    # produced a route whose "quote id" was really a request id. Anything
    # later using it as a quote id would be addressing the wrong object.
    # They are stored apart, and a caller asks for the one it means.
    quote_id: str
    zid: str
    source_chain: str
    destination_chain: str
    source_token: str
    destination_token: str
    source_amount_raw: int
    expected_out_raw: int
    minimum_out_raw: int
    # OUR policy marker, never sent anywhere. See GAS_POLICY_USER.
    gas_policy: str = GAS_POLICY_USER
    # The base58 public key sent as the provider's `gasPayer`, when there is
    # an alternative fee payer. Empty means the parameter is omitted.
    provider_gas_payer: str = ''
    allowance_target: str = ''
    tx_to: str = ''
    tx_data: str = ''
    tx_value: int = 0
    tx_gas: int = 0
    serialized_transaction: str = ''      # SVM origin legs come pre-built
    estimated_seconds: int = 0
    bridge_provider: str = ''
    fees_raw: dict = field(default_factory=dict)
    # 0x's own gas figures for this route, kept verbatim. They are what makes
    # a native-gas number an ESTIMATE FROM THE PROVIDER rather than a constant
    # this repository made up.
    gas_costs_raw: object = field(default_factory=dict)
    needs_allowance: bool = False
    # 0x sets `simulationIncomplete` when it could NOT simulate the
    # transaction it is handing back -- most often because the taker has not
    # approved the token yet, sometimes because the route itself could not be
    # dry-run. Absent means it did not raise the flag; only an explicit true
    # sets this. It is recorded rather than used to reject, because the honest
    # first-trade sequence (approve, then execute) legitimately produces an
    # unsimulatable quote, and the bytes are checked directly either way by
    # verify_source_calldata(). Preflight reports it, so a route that is going
    # to carry real money is never signed off on an unsimulated quote.
    simulation_incomplete: bool = False
    # What the response said about a co-signer: {required, path, value,
    # reason}. Carried on the route so the refusal happens once, at
    # verification, and can name the exact field it found.
    ephemeral_signer: dict = field(default_factory=lambda: {'required': False})

    @property
    def ephemeral_signer_required(self) -> bool:
        return bool((self.ephemeral_signer or {}).get('required'))
    raw: dict = field(default_factory=dict)

    @property
    def is_svm_source(self) -> bool:
        return R.get_chain(self.source_chain).kind == 'svm'

    def loss_raw(self) -> int:
        """What the bridge keeps, in source units.

        Only meaningful because both sides are USDC: a dollar in and a dollar
        out. This is NOT a general amount comparison and must not become one
        if a non-stable asset is ever bridged here.
        """
        src = R.get_chain(self.source_chain).stable
        dst = R.get_chain(self.destination_chain).stable
        s_dec, d_dec = src.require_decimals(), dst.require_decimals()
        # Compare at the finer of the two scales rather than dividing, so no
        # precision is thrown away before the subtraction.
        scale = max(s_dec, d_dec)
        sent = self.source_amount_raw * (10 ** (scale - s_dec))
        got = self.minimum_out_raw * (10 ** (scale - d_dec))
        return sent - got

    def loss_usd(self) -> Decimal:
        """The bridge's cost in dollars, rounded UP to the cent.

        Up, because this is a cost and the engine's whole arithmetic depends
        on costs never being understated -- a bridge quoted a third of a cent
        light is a third of a cent the ceiling did not reserve.
        """
        src = R.get_chain(self.source_chain).stable
        scale = max(src.require_decimals(),
                    R.get_chain(self.destination_chain).stable.require_decimals())
        exact = Decimal(self.loss_raw()) / (Decimal(10) ** scale)
        return exact.quantize(Decimal('0.01'), rounding=ROUND_UP)

    def cost_lines(self) -> list:
        """The bridge's cost, as the engine's own cost model sees it.

        One line, not a breakdown of the provider's fee objects. Those are in
        several different tokens and none of them is a USD total, so adding
        them up would mean inventing exchange rates. The difference between
        what goes in and what is guaranteed out is a real number in dollars
        and it already contains all of them.
        """
        loss = self.loss_usd()
        if loss <= 0:
            return []
        return [CostLine(kind=KIND_BRIDGE_FEE, usd=loss, payer='user',
                         source=f'{self.provider}:{self.bridge_provider or "bridge"}',
                         detail=f'{self.source_chain} -> {self.destination_chain}')]


@dataclass(frozen=True)
class CrossChainStatus:
    """What the provider says has happened so far."""
    status: str
    source_on_chain: bool
    filled: bool
    failed: bool
    destination_tx_hash: str = ''
    bridge_tx_hash: str = ''
    settled_out_raw: Optional[int] = None
    failure_reason: str = ''
    recovery: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


class ZeroExCrossChain:
    """0x's Cross-Chain API, adapted.

    `fetch_quote` and `fetch_status` perform the real requests and are
    injected rather than imported, exactly as ZeroExProvider takes `fetch` --
    so this module stays free of the app, and a test hands it a recorded
    response instead of a network.
    """
    name = '0x'

    def __init__(self, fetch_quote: Callable, fetch_status: Callable):
        self._fetch_quote = fetch_quote
        self._fetch_status = fetch_status
        # Set when a status call carrying quoteId was refused and the
        # verified two-parameter shape had to be used instead. Read by the
        # smoke script so an operator can see which shape the live API takes.
        self.last_quote_id_status_error = ''
        self._asked_amount = 0

    # ── quoting ──────────────────────────────────────────────────────────
    def get_quote(self, *, source_chain: str, destination_chain: str,
                  source_amount_raw: int, origin_address: str,
                  destination_address: str, slippage_bps: int = 100,
                  alternative_gas_payer: str = '',
                  extra_allowed_spenders: frozenset = frozenset(),
                  settler_lookup: Optional[Callable] = None) -> CrossChainRoute:
        """Price one USDC move, and refuse anything that does not check out.

        `alternative_gas_payer` is a base58 Solana public key for the case
        where some OTHER wallet pays the network fee and co-signs. OrcAgent
        never passes one -- the user pays their own gas -- so it is empty and
        the provider's `gasPayer` parameter is OMITTED, which is what 0x's own
        self-paid example does. Sending a made-up value there instead is how
        this integration previously transmitted the literal string 'user' to a
        parameter that expects a public key.
        """
        if source_chain == destination_chain:
            raise CrossChainError(
                'a cross-chain quote was asked for a single chain — the caller '
                'should have taken the direct route')
        src = R.get_chain(source_chain)
        dst = R.get_chain(destination_chain)
        source_amount_raw = _positive_int(source_amount_raw, 'source amount')

        if alternative_gas_payer:
            # If one is ever passed it has to be a real Solana public key,
            # because that is the only thing the parameter accepts. And it is
            # only meaningful on a Solana origin: there is no documented EVM
            # equivalent, so it is not sent on one.
            if src.kind != 'svm':
                raise CrossChainError(
                    'an alternative gas payer is a Solana-origin concept; there is '
                    f'no documented equivalent for a {source_chain} origin, so it '
                    f'is not sent')
            if not _SVM_ADDRESS.match(alternative_gas_payer.strip()):
                raise CrossChainError(
                    'an alternative gas payer must be a base58 Solana public key, '
                    f'not {alternative_gas_payer!r}')

        request = {
            'origin_chain': chain_param(source_chain),
            'destination_chain': chain_param(destination_chain),
            'sell_token': src.stable.address,
            'buy_token': dst.stable.address,
            'sell_amount': str(source_amount_raw),
            'origin_address': origin_address,
            'destination_address': destination_address,
            'slippage_bps': int(slippage_bps),
        }
        # Present only when there really is an alternative payer. An optional
        # parameter that is always sent is not optional.
        if alternative_gas_payer:
            request['gas_payer'] = alternative_gas_payer.strip()

        # Remembered for the no-liquidity answer, which has to be able to say
        # WHICH amount could not be served -- that is the part that changes.
        self._asked_amount = source_amount_raw
        try:
            data = self._fetch_quote(**request)
        except Exception as e:
            raise CrossChainError(f'cross-chain quote failed: {e}') from e

        q, data = self._envelope(data, source_chain, destination_chain)
        route = self._normalise(
            data, q, source_chain=source_chain, destination_chain=destination_chain,
            source_amount_raw=source_amount_raw,
            provider_gas_payer=alternative_gas_payer.strip())
        self.verify_route(route, expected_recipient=destination_address,
                          expected_sender=origin_address,
                          extra_allowed_spenders=extra_allowed_spenders,
                          settler_lookup=settler_lookup)
        return route

    # Response envelopes this integration recognises. Exactly one, because
    # exactly one is verified: `quotes`, from 0x's published Zod schema
    # (CrossChainQuotesResponseSchema, discriminated on liquidityAvailable).
    #
    # It is a named constant rather than an inline literal so that adding a
    # second shape, if 0x ever documents one, is a deliberate one-line change
    # made after reading the documentation -- not a permissive parser that
    # quietly accepts whatever arrives. A response in an unrecognised shape
    # fails closed and says what it saw, which is what makes the smoke script
    # in scripts/ able to tell an operator the API has changed.
    QUOTE_LIST_KEYS = ('quotes',)
    # Keys that have been SEEN in the wild or suggested but are not verified
    # against a current published schema. Their presence is reported by name
    # in the refusal, so nobody has to guess why a response was rejected.
    QUOTE_LIST_KEYS_UNVERIFIED = ('routes',)

    def _envelope(self, data, source_chain: str, destination_chain: str):
        """Pull the first quote out of the response, or fail closed."""
        if not isinstance(data, dict):
            raise CrossChainError('the cross-chain API returned a non-object response')
        if not data.get('liquidityAvailable'):
            # Not an error in the response -- an absence of liquidity. Kept
            # distinct from a malformed envelope on purpose.
            raise NoLiquidity(
                f'no bridge route for {source_chain} -> {destination_chain} at '
                f'this size',
                source_chain=source_chain, destination_chain=destination_chain,
                amount_raw=self._asked_amount, provider=self.name,
                zid=str(data.get('zid') or ''))

        for key in self.QUOTE_LIST_KEYS:
            found = data.get(key)
            if isinstance(found, list) and found:
                q = found[0]
                if not isinstance(q, dict):
                    raise RouteRejected(f'the first entry of {key!r} is not an object')
                return q, data

        seen = [k for k in self.QUOTE_LIST_KEYS_UNVERIFIED
                if isinstance(data.get(k), list)]
        if seen:
            raise RouteRejected(
                f'the response carries {seen[0]!r} rather than '
                f'{self.QUOTE_LIST_KEYS[0]!r}. That may be a current 0x envelope '
                f'this integration has not been updated for — it is refused rather '
                f'than parsed on a guess. Verify against the current documentation '
                f'and add it to QUOTE_LIST_KEYS.')
        if any(k in data for k in self.QUOTE_LIST_KEYS):
            raise NoLiquidity(
                f'no bridge route for {source_chain} -> {destination_chain} at '
                f'this size',
                source_chain=source_chain, destination_chain=destination_chain,
                amount_raw=self._asked_amount, provider=self.name,
                zid=str(data.get('zid') or ''))
        raise RouteRejected(
            f'the response has liquidity but no recognised list of quotes; its keys '
            f'are {sorted(data)[:12]}')

    def _normalise(self, data: dict, q: dict, *, source_chain: str,
                   destination_chain: str, source_amount_raw: int,
                   provider_gas_payer: str) -> CrossChainRoute:
        src = R.get_chain(source_chain)
        dst = R.get_chain(destination_chain)

        expected_out = _positive_int(q.get('buyAmount'), 'buyAmount')
        minimum_out = _positive_int(q.get('minBuyAmount') or q.get('buyAmount'),
                                    'minBuyAmount')

        # transaction is nested by chain type: EVM gives {to,data,gas,gasPrice,
        # value}; SVM gives {serializedTransaction}. Read both shapes rather
        # than assuming which one a chain returns.
        tx = q.get('transaction') or {}
        if not isinstance(tx, dict):
            tx = {}
        details = tx.get('details') if isinstance(tx.get('details'), dict) else tx

        steps = q.get('steps') if isinstance(q.get('steps'), list) else []
        bridge_step = next((s for s in steps
                            if isinstance(s, dict) and s.get('type') == 'bridge'), None)

        issues = q.get('issues') or data.get('issues') or {}
        if not isinstance(issues, dict):
            issues = {}

        # The spender the RESPONSE nominates. 0x documents two places it can
        # appear -- the top-level allowanceTarget, and issues.allowance.spender
        # -- so both are read and, when both are present, they have to agree.
        # Taking the tx target as the spender instead is precisely the mistake
        # that drained approvals to a Settler in August 2025.
        allowance_issue = issues.get('allowance') if isinstance(
            issues.get('allowance'), dict) else {}
        spender_top = str(data.get('allowanceTarget') or '')
        spender_issue = str(allowance_issue.get('spender') or '')
        if spender_top and spender_issue and not _same_address(spender_top, spender_issue):
            raise RouteRejected(
                f'the response names two different spenders — allowanceTarget '
                f'{spender_top} and issues.allowance.spender {spender_issue}. One '
                f'of them is wrong and approving either is a guess')

        # THE TOKENS THE RESPONSE ITSELF NAMES.
        # These used to be filled in from the registry and then "verified"
        # against the registry, which is a tautology: the response's own
        # sellToken and buyToken were never looked at. A route that bridged to
        # something other than the destination's dollar asset would have
        # passed, and the destination swap would then have tried to spend an
        # asset that was not there.
        #
        # Empty is allowed and means the response did not echo them; the
        # registry value stands in, and verify_route's other checks still
        # apply. A PRESENT and DIFFERENT value is refused.
        echoed_sell = str(q.get('sellToken') or data.get('sellToken') or '')
        echoed_buy = str(q.get('buyToken') or data.get('buyToken') or '')

        return CrossChainRoute(
            provider=self.name,
            quote_id=str(q.get('quoteId') or ''),
            zid=str(data.get('zid') or ''),
            source_chain=source_chain,
            destination_chain=destination_chain,
            source_token=echoed_sell or src.stable.address,
            destination_token=echoed_buy or dst.stable.address,
            source_amount_raw=source_amount_raw,
            expected_out_raw=expected_out,
            minimum_out_raw=minimum_out,
            gas_policy=(GAS_POLICY_ALTERNATIVE if provider_gas_payer
                        else GAS_POLICY_USER),
            provider_gas_payer=provider_gas_payer,
            allowance_target=spender_top or spender_issue,
            tx_to=str(details.get('to') or ''),
            tx_data=str(details.get('data') or ''),
            tx_value=int(str(details.get('value') or 0) or 0),
            tx_gas=int(str(details.get('gas') or 0) or 0),
            serialized_transaction=str(details.get('serializedTransaction') or ''),
            estimated_seconds=int(q.get('estimatedTimeSeconds') or 0),
            bridge_provider=str((bridge_step or {}).get('provider') or ''),
            gas_costs_raw=q.get('gasCosts') if isinstance(q.get('gasCosts'), (dict, list)) else {},
            fees_raw=q.get('fees') if isinstance(q.get('fees'), dict) else {},
            needs_allowance=bool(allowance_issue),
            simulation_incomplete=(q.get('simulationIncomplete') is True
                                   or data.get('simulationIncomplete') is True),
            ephemeral_signer=ephemeral_signer_requirement(q, data),
            raw=q,
        )

    # ── the part that stands between a response and the money ────────────
    def verify_route(self, route: CrossChainRoute, *, expected_recipient: str,
                     expected_sender: str = '',
                     extra_allowed_spenders: frozenset = frozenset(),
                     settler_lookup: Optional[Callable] = None) -> None:
        """Refuse a route that is not the one we asked for.

        Each check below is a way a forged or corrupted response could take
        the user's money, so none of them is a formality and none of them is
        repaired rather than refused.
        """
        src = R.get_chain(route.source_chain)
        dst = R.get_chain(route.destination_chain)

        # The tokens. A route that sells something other than the source
        # chain's verified USDC is selling the wrong asset; one that buys
        # something other than the destination's is delivering an asset the
        # rest of this trade cannot spend. Both are checked against the
        # registry, which is keyed on address -- so a token merely NAMED USDC
        # cannot satisfy either.
        if not _same_address(route.source_token, src.stable.address):
            raise RouteRejected(
                f'route sells {route.source_token} on {route.source_chain}, but that '
                f"chain's dollar asset is {src.stable.symbol} at {src.stable.address}")
        # THE INVARIANT THE DESTINATION SWAP DEPENDS ON.
        # This engine's design is: source stable -> destination STABLE, and
        # then OrcAgent's own swap buys the token. That second swap spends the
        # destination chain's dollar asset, so if the bridge delivered
        # anything else -- including the final token, if 0x were ever asked
        # for a route that ends in it -- the swap would try to spend an asset
        # that is not there, or sell a token the user already holds.
        #
        # Checked against what the RESPONSE says it delivers, not against what
        # we asked for.
        if not _same_address(route.destination_token, dst.stable.address):
            raise RouteRejected(
                f'route delivers {route.destination_token} on {route.destination_chain}, '
                f'but this engine bridges into {dst.stable.symbol} at '
                f'{dst.stable.address} and then swaps separately. A route ending in '
                f'anything else would be swapped a second time')

        # The recipient. This is the single most important line here: a route
        # that delivers to an address other than the user's own wallet is a
        # theft, whatever else about it is correct.
        echoed = route.raw.get('destinationAddress') or ''
        if echoed and not _same_address(echoed, expected_recipient):
            raise RouteRejected(
                f'route would deliver to {echoed}, not to the wallet that asked '
                f'({expected_recipient})')
        if expected_sender:
            echoed_from = route.raw.get('originAddress') or ''
            if echoed_from and not _same_address(echoed_from, expected_sender):
                raise RouteRejected(
                    f'route would send from {echoed_from}, not from {expected_sender}')

        # Amounts. A sellAmount that came back different from the one asked
        # for means the provider re-sized the trade, and the ceiling was
        # computed against our number, not theirs.
        echoed_sell = route.raw.get('sellAmount')
        if echoed_sell is not None and int(str(echoed_sell)) != route.source_amount_raw:
            raise RouteRejected(
                f'route sells {echoed_sell}, not the {route.source_amount_raw} asked for')
        if route.minimum_out_raw > route.expected_out_raw:
            raise RouteRejected(
                'route guarantees more than it expects to deliver, which is not a '
                'guarantee — the response is inconsistent')

        # The bridge cannot deliver more dollars than it was given. One that
        # claims to is either misread or lying, and either way the number
        # would flow straight into the user's quoted output.
        if route.loss_raw() < 0:
            raise RouteRejected(
                'route claims to deliver more than it takes in — refusing rather '
                'than believing a free lunch')

        # ── a co-signer this integration does not have ──
        # Refused before anything else about the transaction is considered,
        # because no amount of the rest being correct makes a route we cannot
        # sign executable.
        if route.ephemeral_signer_required:
            info = route.ephemeral_signer or {}
            raise RouteUnsupported(
                f'this route needs a freshly generated Solana co-signer: '
                f'{info.get("path") or "an ephemeral signer field"} = '
                f'{info.get("value") or "?"}. A key would have to be created per '
                f'quote, used to sign alongside the user, survive a restart and '
                f'then be destroyed. The field name and signing order could not '
                f'be verified against a reachable 0x specification, so the route '
                f'is refused rather than half-attempted — a half-built co-signer '
                f'strands a bridge mid-flight. Base <-> Solana does not have to '
                f'use this bridge: 0x\'s own EVM -> Solana example signs with the '
                f'EVM key alone and needs no co-signer at all')

        # The EVM call target and the spender. Approving a spender is handing
        # it the user's USDC, so an address that is not an address at all is
        # refused rather than passed to a contract call.
        if src.kind == 'evm':
            if not _valid_address(route.source_chain, route.tx_to):
                raise RouteRejected(f'route has no usable transaction target: {route.tx_to!r}')
            if not route.tx_data.startswith('0x'):
                raise RouteRejected('route has no usable calldata')
            # A target that IS the token contract means the calldata is a
            # direct ERC-20 call the bridge has no business making on the
            # user's behalf -- a transfer to wherever the calldata says.
            if _same_address(route.tx_to, src.stable.address):
                raise RouteRejected(
                    'route would call the USDC contract itself — that is a token '
                    'transfer wearing a bridge\'s name, not a bridge')
            if route.tx_value < 0:
                raise RouteRejected('route attaches a negative native value')
            self._verify_spender(route, extra_allowed_spenders, settler_lookup)
            # And finally the bytes themselves. Everything above this line
            # reads the quote's own fields; this reads what the transaction
            # will actually do, which is the only account that settles.
            verify_source_calldata(route)
        else:
            if not route.serialized_transaction:
                raise RouteRejected(
                    'route has no serialized transaction for a Solana origin leg')

        # OUR policy marker, checked against OUR policy. Never confused with
        # the provider's gasPayer parameter, which is a public key and is
        # omitted entirely when the user pays.
        if route.gas_policy != GAS_POLICY_USER:
            raise RouteRejected(
                f'route is marked {route.gas_policy} — this engine only executes '
                f'routes the user pays for')

    def _verify_spender(self, route: CrossChainRoute, extra_allowed: frozenset,
                        settler_lookup: Optional[Callable]) -> None:
        """Decide whether this address may be given the user's USDC.

        An allowance is not a detail of a transaction; it is a standing
        permission that outlives it. So the question is never "did the
        response say so" -- it did, that is where the address came from --
        but "is this one of the addresses that legitimately holds one".
        """
        if not route.needs_allowance and not route.allowance_target:
            return                      # nothing will be approved
        spender = (route.allowance_target or '').strip()
        if not _valid_address(route.source_chain, spender):
            raise RouteRejected(f'route names an unusable spender: {spender!r}')

        low = spender.lower()
        if low == ZEROX_SETTLER_REGISTRY:
            raise RouteRejected(
                'route would have the user approve the 0x Settler deployer/registry. '
                'Settler contracts neither need nor support allowances, and '
                'approvals mis-scoped to one are what an August 2025 exploit drained')
        if _same_address(spender, route.tx_to) and low not in CANONICAL_ALLOWANCE_TARGETS:
            # AllowanceHolder is legitimately both spender and call target,
            # and it is in the allowlist. Anything ELSE that asks to be
            # approved AND called is asking for a standing permission on the
            # contract that executes -- which is the Settler shape.
            raise RouteRejected(
                f'route would have the user approve {spender}, the same contract the '
                f'transaction calls, and it is not a recognised allowance contract. '
                f'That is the shape of approving a Settler')

        if settler_lookup is not None:
            # 0x says to ask the registry rather than hardcode. Best effort:
            # a lookup that fails is not evidence of safety, so it does not
            # grant permission -- the allowlist below still decides.
            try:
                if settler_lookup(route.source_chain, spender):
                    raise RouteRejected(
                        f'{spender} is a current 0x Settler on {route.source_chain}, '
                        f'and Settler must never be given an allowance')
            except RouteRejected:
                raise
            except Exception:
                pass

        if low in CANONICAL_ALLOWANCE_TARGETS:
            return
        if low in {a.lower() for a in extra_allowed}:
            return
        raise RouteUnsupported(
            f'{spender} is not a recognised allowance contract on '
            f'{route.source_chain}. Permit2 and AllowanceHolder are recognised '
            f'automatically; a bridge that needs its own spender has to be added '
            f'deliberately (CROSSCHAIN_ALLOWED_SPENDERS) after somebody has '
            f'looked at what it is. An approval is a standing permission, so it '
            f'is not granted on the say-so of the response that asked for it')

    # ── status ───────────────────────────────────────────────────────────
    def get_status(self, *, source_chain: str, source_tx_hash: str,
                   quote_id: str = '') -> CrossChainStatus:
        """Ask what has happened, and never guess when the answer is unfamiliar.

        `quote_id` is 0x's `quoteId` for the specific quote that was executed
        -- never the top-level `zid`, which identifies the request. It is sent
        when we have one, because a status lookup that can name the quote is
        more precise than one that can only name a transaction.

        It is sent DEFENSIVELY. 0x's published request schema for this
        endpoint lists only originChain and originTxHash, and its own example
        sends only those two; the documentation that recommends quoteId could
        not be reached from the build environment. So the call is made with it
        and, if the endpoint refuses the request, retried without it. That way
        an extra parameter can never be the reason a bridge stops being
        tracked -- which, for a trade holding a user's reservation, is the
        expensive failure.
        """
        if not source_tx_hash:
            raise CrossChainError('cannot ask about a bridge with no origin transaction')
        base = {'origin_chain': chain_param(source_chain),
                'origin_tx_hash': source_tx_hash}
        data = None
        if quote_id:
            try:
                data = self._fetch_status(quote_id=quote_id, **base)
            except Exception as e:
                # Fall back to the shape that IS verified, and say so, rather
                # than letting an unverified parameter end the tracking.
                self.last_quote_id_status_error = str(e)[:200]
                data = None
        if data is None:
            try:
                data = self._fetch_status(**base)
            except Exception as e:
                raise CrossChainError(f'cross-chain status failed: {e}') from e
        if not isinstance(data, dict):
            raise CrossChainError('the status endpoint returned a non-object response')

        status = str(data.get('status') or '').strip().lower()
        if status not in ALL_STATUSES:
            # An unrecognised status keeps the trade where it is. That costs
            # time; deciding it means 'filled' could cost the trade.
            status = UNKNOWN

        txs = data.get('transactions') if isinstance(data.get('transactions'), list) else []
        dest_hash = ''
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            h = str(tx.get('txHash') or '')
            if h and not _same_address(h, source_tx_hash):
                dest_hash = h
                break

        settled = None
        for step in (data.get('steps') if isinstance(data.get('steps'), list) else []):
            if not isinstance(step, dict):
                continue
            if step.get('type') == 'bridge' and step.get('settledBuyAmount') is not None:
                try:
                    settled = int(str(step['settledBuyAmount']))
                except (TypeError, ValueError):
                    settled = None

        failure = data.get('failure') if isinstance(data.get('failure'), dict) else {}
        return CrossChainStatus(
            status=status,
            source_on_chain=status in SOURCE_IS_ON_CHAIN,
            filled=status == BRIDGE_FILLED,
            failed=status in (BRIDGE_FAILED, ORIGIN_REVERTED),
            destination_tx_hash=dest_hash,
            bridge_tx_hash=str(data.get('bridge') or ''),
            settled_out_raw=settled,
            failure_reason=str(failure.get('reason') or ''),
            recovery=failure.get('recovery') if isinstance(failure.get('recovery'), dict) else {},
            raw=data,
        )


# ── Solana transaction versions ──────────────────────────────────────────
def check_solana_tx_version(serialized_b64: str, parse) -> object:
    """Parse a provider-returned Solana transaction, or refuse the route.

    `parse` takes raw bytes and returns something with .message.version --
    solders' VersionedTransaction.from_bytes in production, a stub in a test.
    Injected so this module stays free of a Solana dependency.

    WHY THIS IS A GATE RATHER THAN A TRY/EXCEPT AT SIGNING TIME
    A transaction format the local library cannot read has to stop the trade
    BEFORE a key is decrypted and before anything is broadcast. Discovering it
    at signing time means the failure happens with the user's key in memory
    and a reservation held, for a reason nobody can read off the error.

    What is NOT done here, deliberately: no attempt to repair, downgrade or
    re-serialise the provider's bytes. Those bytes are what the bridge will
    honour; rebuilding them locally to make a parser happy produces a
    transaction that is no longer the one that was quoted.
    """
    if not serialized_b64:
        raise RouteRejected('the route carries no serialized transaction')
    import base64
    try:
        raw = base64.b64decode(serialized_b64, validate=True)
    except Exception as e:
        raise RouteRejected(f'the serialized transaction is not valid base64: {e}')
    try:
        tx = parse(raw)
    except Exception as e:
        raise RouteUnsupported(
            f'this route returned a Solana transaction the local library cannot '
            f'parse ({type(e).__name__}: {e}). It is refused rather than signed, '
            f'and its bytes are not rebuilt locally — a reconstructed transaction '
            f'is not the one that was quoted')
    version = getattr(getattr(tx, 'message', None), 'version', None)
    if version is None:
        version = getattr(tx, 'version', None)
    if version not in SUPPORTED_SOLANA_TX_VERSIONS:
        raise RouteUnsupported(
            f'this route returned a Solana transaction of version {version!r}; '
            f'this integration signs {SUPPORTED_SOLANA_TX_VERSIONS} and refuses '
            f'anything else before signing rather than after')
    return tx


# ── what the source transaction actually does ────────────────────────────
# The live Base -> Solana route calls AllowanceHolder with this selector:
#
#     0x2213bc0b  exec(address operator, address token, uint256 amount,
#                      address target, bytes data)
#
# verified by keccak against the signature, not read off a comment somewhere.
#
# WHY DECODING IT MATTERS MORE THAN CHECKING THE TARGET
# Knowing tx.to is AllowanceHolder says who is called. It says nothing about
# what they are asked to do. AllowanceHolder.exec pulls `amount` of `token`
# from the caller, grants `operator` a TRANSIENT allowance for exactly that,
# calls `target` with `data`, and clears it again.
#
# So the blast radius of the whole transaction is precisely (token, amount) --
# the two arguments sitting in plain sight at the front of the calldata. A
# route that quoted 2 USDC and encoded 2000 would be caught here and nowhere
# else: the quote's own sellAmount field would still say 2, and every check
# that reads the quote rather than the bytes would pass it.
#
# The transient allowance is also why `operator` is not allowlisted. It is a
# Settler, Settler addresses are explicitly not hardcodeable, and the
# permission it receives dies with the call. Bounding (token, amount) bounds
# the loss whoever the operator is.
ALLOWANCE_HOLDER_EXEC_SELECTOR = '0x2213bc0b'

# What is NOT done here, deliberately: nothing decodes or re-encodes the inner
# `data` argument, and nothing is rebuilt. Those bytes are the bridge's own
# call and they are what 0x quoted; a locally reconstructed version is a
# different transaction wearing the same intent.


def _word(body: str, index: int) -> str:
    start = index * 64
    word = body[start:start + 64]
    if len(word) < 64:
        raise RouteRejected(
            f'the calldata ends mid-argument at word {index} — it is truncated '
            f'or malformed, and a partially readable transaction is not one to '
            f'sign')
    return word


def _word_address(body: str, index: int) -> str:
    word = _word(body, index)
    if word[:24] != '0' * 24:
        raise RouteRejected(
            f'calldata word {index} is not a clean address — its upper bytes '
            f'are set, which an ABI-encoded address never has')
    return '0x' + word[24:]


def _word_uint(body: str, index: int) -> int:
    try:
        return int(_word(body, index), 16)
    except ValueError:
        raise RouteRejected(f'calldata word {index} is not a number')


def decode_allowance_holder_exec(calldata: str) -> dict:
    """Read the four leading arguments of AllowanceHolder.exec.

    Returns {selector, operator, token, amount, target}. The trailing `bytes
    data` argument is deliberately not decoded: it is the bridge's own call,
    this integration has no business interpreting it, and every attempt to
    would be a second implementation of somebody else's protocol.
    """
    if not isinstance(calldata, str) or not calldata.startswith('0x'):
        raise RouteRejected('the transaction has no usable calldata')
    selector = calldata[:10].lower()
    if selector != ALLOWANCE_HOLDER_EXEC_SELECTOR:
        raise RouteRejected(
            f'the transaction calls {selector} on the allowance contract, not '
            f'{ALLOWANCE_HOLDER_EXEC_SELECTOR} (exec). This integration signs '
            f'exec and nothing else — an unrecognised function on a contract '
            f'that holds allowances is exactly the thing not to sign on trust')
    body = calldata[10:]
    return {
        'selector': selector,
        'operator': _word_address(body, 0),
        'token': _word_address(body, 1),
        'amount': _word_uint(body, 2),
        'target': _word_address(body, 3),
    }


def verify_source_calldata(route: CrossChainRoute) -> dict:
    """Check that the bytes agree with the quote they arrived with.

    Only for an EVM source going through a recognised allowance contract.
    Anything else returns {'checked': False} with the reason, because a check
    that quietly does nothing is worse than no check.
    """
    src = R.get_chain(route.source_chain)
    if src.kind != 'evm':
        return {'checked': False, 'reason': 'not an EVM source'}
    if (route.tx_to or '').lower() not in CANONICAL_ALLOWANCE_TARGETS:
        # A different execution target is a different ABI. It is not decoded
        # on a guess; _verify_spender has already refused anything that is not
        # either canonical or deliberately pinned by an operator.
        return {'checked': False,
                'reason': f'target {route.tx_to} is not a published allowance '
                          f'contract, so its calldata shape is not assumed'}

    decoded = decode_allowance_holder_exec(route.tx_data)

    # THE TOKEN THAT WILL BE PULLED. Must be the source chain's dollar asset,
    # by address, from the registry.
    if not _same_address(decoded['token'], src.stable.address):
        raise RouteRejected(
            f'the calldata would pull {decoded["token"]} from the wallet, not '
            f'{src.stable.symbol} at {src.stable.address}. The quote says one '
            f'asset and the bytes say another; the bytes are what executes')

    # THE AMOUNT THAT WILL BE PULLED. Must be exactly what was quoted. This is
    # the check that catches a route quoting 2 and encoding 2000.
    if decoded['amount'] != route.source_amount_raw:
        raise RouteRejected(
            f'the calldata would pull {decoded["amount"]} but the quote sold '
            f'{route.source_amount_raw}. A transaction that spends more than '
            f'the quote it came with is refused, whatever the difference')

    # The operator receiving the transient allowance must at least be an
    # address, and must not be the token itself -- that combination would mean
    # approving the asset contract to move the asset, which is nonsense the
    # rest of the checks would not otherwise catch.
    if not _EVM_ADDRESS.match(decoded['operator']):
        raise RouteRejected(f'the calldata names an unusable operator: {decoded["operator"]}')
    if _same_address(decoded['operator'], decoded['token']):
        raise RouteRejected(
            'the calldata would grant the token contract an allowance over '
            'itself, which is not a thing any real route does')

    return {'checked': True, **decoded}
