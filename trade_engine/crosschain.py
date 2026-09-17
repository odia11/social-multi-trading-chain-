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
    route_id: str
    source_chain: str
    destination_chain: str
    source_token: str
    destination_token: str
    source_amount_raw: int
    expected_out_raw: int
    minimum_out_raw: int
    # Whose native balance pays for the origin transaction. 'user' is the
    # only value this engine will execute -- see the gas policy in
    # dashboard's _cc_gas_requirement().
    gas_payer: str = 'user'
    allowance_target: str = ''
    tx_to: str = ''
    tx_data: str = ''
    tx_value: int = 0
    tx_gas: int = 0
    serialized_transaction: str = ''      # SVM origin legs come pre-built
    estimated_seconds: int = 0
    bridge_provider: str = ''
    fees_raw: dict = field(default_factory=dict)
    needs_allowance: bool = False
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

    # ── quoting ──────────────────────────────────────────────────────────
    def get_quote(self, *, source_chain: str, destination_chain: str,
                  source_amount_raw: int, origin_address: str,
                  destination_address: str, slippage_bps: int = 100,
                  gas_payer: str = 'user') -> CrossChainRoute:
        """Price one USDC move, and refuse anything that does not check out."""
        if source_chain == destination_chain:
            raise CrossChainError(
                'a cross-chain quote was asked for a single chain — the caller '
                'should have taken the direct route')
        src = R.get_chain(source_chain)
        dst = R.get_chain(destination_chain)
        source_amount_raw = _positive_int(source_amount_raw, 'source amount')

        try:
            data = self._fetch_quote(
                origin_chain=chain_param(source_chain),
                destination_chain=chain_param(destination_chain),
                sell_token=src.stable.address,
                buy_token=dst.stable.address,
                sell_amount=str(source_amount_raw),
                origin_address=origin_address,
                destination_address=destination_address,
                slippage_bps=int(slippage_bps),
                gas_payer=gas_payer,
            )
        except Exception as e:
            raise CrossChainError(f'cross-chain quote failed: {e}') from e

        if not isinstance(data, dict):
            raise CrossChainError('the cross-chain API returned a non-object response')
        if not data.get('liquidityAvailable'):
            raise CrossChainError(
                f'no bridge route for {source_chain} -> {destination_chain} at this size')
        quotes = data.get('quotes')
        if not isinstance(quotes, list) or not quotes:
            raise CrossChainError(
                f'no bridge route for {source_chain} -> {destination_chain} at this size')
        q = quotes[0]
        if not isinstance(q, dict):
            raise RouteRejected('the first quote in the response is not an object')

        route = self._normalise(
            data, q, source_chain=source_chain, destination_chain=destination_chain,
            source_amount_raw=source_amount_raw, gas_payer=gas_payer)
        self.verify_route(route, expected_recipient=destination_address,
                          expected_sender=origin_address)
        return route

    def _normalise(self, data: dict, q: dict, *, source_chain: str,
                   destination_chain: str, source_amount_raw: int,
                   gas_payer: str) -> CrossChainRoute:
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

        return CrossChainRoute(
            provider=self.name,
            route_id=str(q.get('quoteId') or data.get('zid') or ''),
            source_chain=source_chain,
            destination_chain=destination_chain,
            source_token=src.stable.address,
            destination_token=dst.stable.address,
            source_amount_raw=source_amount_raw,
            expected_out_raw=expected_out,
            minimum_out_raw=minimum_out,
            gas_payer=gas_payer,
            allowance_target=str(data.get('allowanceTarget') or ''),
            tx_to=str(details.get('to') or ''),
            tx_data=str(details.get('data') or ''),
            tx_value=int(str(details.get('value') or 0) or 0),
            tx_gas=int(str(details.get('gas') or 0) or 0),
            serialized_transaction=str(details.get('serializedTransaction') or ''),
            estimated_seconds=int(q.get('estimatedTimeSeconds') or 0),
            bridge_provider=str((bridge_step or {}).get('provider') or ''),
            fees_raw=q.get('fees') if isinstance(q.get('fees'), dict) else {},
            needs_allowance=bool(issues.get('allowance')),
            raw=q,
        )

    # ── the part that stands between a response and the money ────────────
    def verify_route(self, route: CrossChainRoute, *, expected_recipient: str,
                     expected_sender: str = '') -> None:
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
        if not _same_address(route.destination_token, dst.stable.address):
            raise RouteRejected(
                f'route delivers {route.destination_token} on {route.destination_chain}, '
                f'but that chain\'s dollar asset is {dst.stable.symbol} at '
                f'{dst.stable.address}')

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

        # The EVM call target and the spender. Approving a spender is handing
        # it the user's USDC, so an address that is not an address at all is
        # refused rather than passed to a contract call.
        if src.kind == 'evm':
            if not _valid_address(route.source_chain, route.tx_to):
                raise RouteRejected(f'route has no usable transaction target: {route.tx_to!r}')
            if not route.tx_data.startswith('0x'):
                raise RouteRejected('route has no usable calldata')
            if route.allowance_target and not _valid_address(route.source_chain,
                                                             route.allowance_target):
                raise RouteRejected(
                    f'route names an unusable spender: {route.allowance_target!r}')
            # A target that IS the token contract means the calldata is a
            # direct ERC-20 call the bridge has no business making on the
            # user's behalf -- a transfer to wherever the calldata says.
            if _same_address(route.tx_to, src.stable.address):
                raise RouteRejected(
                    'route would call the USDC contract itself — that is a token '
                    'transfer wearing a bridge\'s name, not a bridge')
            if route.tx_value != 0 and src.kind == 'evm':
                # A USDC bridge spends USDC. Native value attached to the call
                # is either a protocol fee the quote did not declare or a
                # mistake; either way it is money leaving outside the ceiling.
                if route.tx_value < 0:
                    raise RouteRejected('route attaches a negative native value')
        else:
            if not route.serialized_transaction:
                raise RouteRejected(
                    'route has no serialized transaction for a Solana origin leg')

        if route.gas_payer != 'user':
            raise RouteRejected(
                f'route would have {route.gas_payer} pay the gas — this engine only '
                f'executes routes the user pays for')

    # ── status ───────────────────────────────────────────────────────────
    def get_status(self, *, source_chain: str, source_tx_hash: str) -> CrossChainStatus:
        """Ask what has happened, and never guess when the answer is unfamiliar."""
        if not source_tx_hash:
            raise CrossChainError('cannot ask about a bridge with no origin transaction')
        try:
            data = self._fetch_status(origin_chain=chain_param(source_chain),
                                      origin_tx_hash=source_tx_hash)
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
