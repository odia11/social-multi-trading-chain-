"""Running a quoted trade, once, with the money claimed before it moves.

WHAT THIS IS FOR
Today eight endpoints execute trades and every one of them does the same
three things wrong: it swaps the full amount the user typed and then charges
the fee on top (so the real spend exceeds what was shown), it checks a
balance and then acts on it (so two trades a second apart can both spend the
same money), and it treats a submitted transaction as a completed trade.
This module is the single path that does not.

THE THREE RULES IT ENFORCES, AND WHY THEY LIVE HERE
1. The swap sells the PURCHASE, not the ceiling. The quote already worked
   out that purchase + fee + gas + slippage reserve = the ceiling exactly.
   An executor that swaps the ceiling breaks it, so the plan handed to the
   executor carries the purchase and the ceiling separately and the engine
   refuses a plan whose parts exceed the ceiling.

2. A retry never produces a second swap. The idempotency key is UNIQUE in
   the schema, so a duplicate request loses that insert and gets the
   original trade back -- WITHOUT the executor being called. The guard is
   the database constraint, not a lookup, because a lookup is two
   statements and two requests can both pass it.

3. A submitted transaction is not a completed trade. An executor that sent
   something but cannot confirm it does not reach COMPLETED; it reaches
   FAILED with needs_investigation set. Nothing here writes a success
   because a broadcast returned a hash.

WHY AN UNCONFIRMED SUBMISSION KEEPS ITS CLAIM
If a swap may have left the wallet, releasing its reservation invites the
next trade to spend the same money a second time. So an unconfirmed
submission settles at the full reserved amount -- the pessimistic
direction -- and is flagged. Only a swap that provably never went out gets
its money back.

WHY THE FEE CANNOT UNDO THE SWAP
Once the swap is confirmed the trade happened. A fee charge that then fails
is a debt to record, not a reason to rewrite history, and certainly not a
reason to re-run the swap. It is written as an actual cost that was not
collected and the trade is flagged.

The app injects everything that touches a chain. This module takes a
connection and two callables. No network, no keys, no app.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from . import ledger as L
from . import registry as _registry
from . import subsidy as S
from .costs import (CostLine, KIND_PLATFORM_FEE, KIND_SOURCE_GAS,
                    PAYER_USER)


class ExecutionError(Exception):
    """The trade could not be started. Nothing was sent."""


class QuoteNotUsable(ExecutionError):
    """The quote expired, was never executable, or does not exist."""


def _d(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v))


# ── what the executor is told, and what it must answer ───────────────────
@dataclass(frozen=True)
class SwapPlan:
    """Everything an executor needs, and nothing it could use to overspend.

    `purchase_usd` is what to sell. `max_spend_usd` is the ceiling it came
    out of, carried so the executor can assert against it rather than having
    to trust that someone upstream did the subtraction.
    """
    trade_id: str
    user_id: int
    wallet: str
    chain: str
    token_address: str
    purchase_usd: Decimal
    max_spend_usd: Decimal
    fee_usd: Decimal
    gas_usd: Decimal
    minimum_output_raw: int
    mode: str
    same_chain: bool


# kw_only: these fields mean very different things and several are bools, so
# a positional call that drifts by one argument reports a revert as a hash and
# is not obviously wrong at the call site. Naming them is not optional.
@dataclass(frozen=True, kw_only=True)
class SwapOutcome:
    """What actually happened on-chain.

    Three outcomes, not two, because they mean different things for the
    user's money:

      not submitted            -- nothing left the wallet; the claim goes back
      submitted and reverted   -- it landed and definitively did not execute;
                                  only gas was spent, so only gas is kept
      submitted, not confirmed -- unknown; the money may be gone, so the claim
                                  is kept and a human is asked

    An executor that cannot tell a revert from a timeout must report the
    third, which is the pessimistic one.
    """
    submitted: bool
    confirmed: bool
    reverted: bool = False
    tx_hash: str = ''
    actual_spend_usd: Optional[Decimal] = None
    actual_gas_usd: Optional[Decimal] = None
    gas_sponsorship_id: Optional[int] = None
    error: str = ''


@dataclass(frozen=True, kw_only=True)
class FeeOutcome:
    """Collected, failed, or dispatched and not yet known.

    The third state is not a hedge. The app's fee charger hands the transfer
    to a background thread and returns before it has happened, so a charger
    that reported `charged=True` would be asserting a collection nobody has
    seen -- the same false success this module refuses everywhere else.
    `pending` says what is actually true: the user's budget carried the fee,
    the transfer is out, and whether it landed is recorded in the fees table
    rather than here.
    """
    charged: bool
    pending: bool = False
    usd: Decimal = Decimal('0')
    tx_hash: str = ''
    error: str = ''

    def __post_init__(self):
        if self.charged and self.pending:
            raise ExecutionError('a fee cannot be both collected and pending')


@dataclass
class ExecutionResult:
    trade_id: str
    state: str
    created: bool                 # False = this was a retry, nothing re-sent
    tx_hash: str = ''
    actual_spend_usd: str = ''
    failure_reason: str = ''
    needs_investigation: bool = False
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'trade_id': self.trade_id,
            'state': self.state,
            'created': self.created,
            'tx_hash': self.tx_hash,
            'actual_spend_usd': self.actual_spend_usd,
            'failure_reason': self.failure_reason,
            'needs_investigation': self.needs_investigation,
            'warnings': list(self.warnings),
            'completed': self.state == L.COMPLETED,
        }


def _quoted_costs(quote_row: dict) -> dict:
    """The cost lines the quote was built from, by kind, as Decimals."""
    import json
    body = json.loads(quote_row['breakdown_json'])
    return {k: _d(v) for k, v in (body.get('costs_by_kind') or {}).items()}


# ── the one path ─────────────────────────────────────────────────────────
def execute_trade(conn, *, quote_id: str, idempotency_key: str, available_usd,
                  swap_executor: Callable[[SwapPlan], SwapOutcome],
                  fee_charger: Optional[Callable[[SwapPlan, SwapOutcome], FeeOutcome]] = None,
                  clock: Callable = time.time) -> ExecutionResult:
    """Execute a stored quote exactly once.

    `available_usd` is the balance the caller read for this user on this
    chain. It is not trusted as permission to spend -- it is the ceiling the
    reservation is taken against, and another trade's outstanding claim is
    subtracted from it inside a write transaction before this one is allowed.
    """
    quote_row = L.load_quote(conn, quote_id)
    usable, why = L.quote_is_usable(quote_row, now=clock())
    if not usable:
        raise QuoteNotUsable(why)

    trade_id, created = L.start_execution(
        conn, idempotency_key=idempotency_key, quote_row=quote_row, now=clock())
    if not created:
        # Rule 2. The insert lost to an identical request, so that request
        # owns this trade. Report what it did; send nothing.
        trade = L.get_trade(conn, trade_id) or {}
        return ExecutionResult(
            trade_id=trade_id, state=trade.get('state', L.CREATED), created=False,
            tx_hash=trade.get('source_tx_hash', '') or '',
            actual_spend_usd=trade.get('actual_spend_usd', '') or '',
            failure_reason=trade.get('failure_reason', '') or '',
            needs_investigation=bool(trade.get('needs_investigation')),
            warnings=['This trade was already started by an identical request; '
                      'nothing was sent a second time.'],
        )

    chain = quote_row['destination_chain']
    ceiling = _d(quote_row['max_spend_usd'])
    purchase = _d(quote_row['token_purchase_usd'])
    total_spend = _d(quote_row['total_cost_usd'])
    costs = _quoted_costs(quote_row)
    warnings: list = []

    def fail(reason: str, *, investigate: bool = False, release: bool = True):
        try:
            if release:
                L.release(conn, trade_id, now=clock())
        except L.LedgerError:
            pass          # nothing was ever reserved
        L.transition(conn, trade_id, L.FAILED, now=clock(),
                     failure_reason=reason[:500],
                     needs_investigation=1 if investigate else 0)
        return ExecutionResult(trade_id=trade_id, state=L.FAILED, created=True,
                               failure_reason=reason, needs_investigation=investigate,
                               warnings=warnings)

    L.transition(conn, trade_id, L.QUOTED, now=clock())
    L.record_costs(conn, trade_id, 'quoted', _cost_lines_from(quote_row), now=clock())
    L.transition(conn, trade_id, L.ROUTE_SELECTED, now=clock())

    # ── the claim, before anything moves ──
    try:
        L.reserve(conn, user_id=quote_row['user_id'], chain=chain, trade_id=trade_id,
                  amount_usd=total_spend, available_usd=_d(available_usd), now=clock())
    except L.InsufficientAvailable as e:
        return fail(str(e), release=False)
    L.transition(conn, trade_id, L.RESERVED, now=clock())

    plan = SwapPlan(
        trade_id=trade_id, user_id=quote_row['user_id'], wallet=quote_row['wallet'],
        chain=chain, token_address=quote_row['token_address'],
        purchase_usd=purchase, max_spend_usd=ceiling,
        fee_usd=costs.get('platform_fee', _d(0)), gas_usd=costs.get('source_gas', _d(0)),
        minimum_output_raw=_minimum_output(quote_row),
        mode=quote_row['mode'], same_chain=bool(quote_row['same_chain']),
    )
    # Rule 1, checked rather than assumed. If the stored quote's own parts do
    # not fit its ceiling, the arithmetic upstream is wrong and executing it
    # would overspend a user who was shown a smaller number.
    if plan.purchase_usd + plan.fee_usd > ceiling:
        return fail(f'quote is inconsistent: purchase ${plan.purchase_usd} plus fee '
                    f'${plan.fee_usd} exceeds the ${ceiling} ceiling', investigate=True)

    L.transition(conn, trade_id, L.EXECUTING, now=clock())
    L.transition(conn, trade_id, L.SWAPPING, now=clock())

    try:
        outcome = swap_executor(plan)
    except Exception as e:
        # An executor that raised may still have broadcast. It cannot be
        # treated as a clean failure, so the money stays claimed and a human
        # is asked to look -- the alternative is releasing a balance that is
        # possibly already spent.
        L.settle(conn, trade_id, total_spend, now=clock())
        L.transition(conn, trade_id, L.FAILED, now=clock(),
                     failure_reason=f'executor raised: {e}'[:500], needs_investigation=1)
        return ExecutionResult(trade_id=trade_id, state=L.FAILED, created=True,
                               failure_reason=f'executor raised: {e}',
                               needs_investigation=True, warnings=warnings)

    if not outcome.submitted:
        return fail(outcome.error or 'the swap was not sent')

    if outcome.reverted:
        # It landed and definitively did not execute. The purchase never
        # happened, so the only money that left the wallet is gas -- and
        # keeping the whole claim would lock up a balance the user still has.
        gas = _d(outcome.actual_gas_usd) if outcome.actual_gas_usd is not None else plan.gas_usd
        L.settle(conn, trade_id, gas, now=clock())
        reason = outcome.error or 'the swap reverted on-chain'
        L.transition(conn, trade_id, L.FAILED, now=clock(),
                     source_tx_hash=outcome.tx_hash, failure_reason=reason[:500],
                     needs_investigation=0)
        return ExecutionResult(trade_id=trade_id, state=L.FAILED, created=True,
                               tx_hash=outcome.tx_hash, failure_reason=reason,
                               needs_investigation=False, warnings=warnings)

    if not outcome.confirmed:
        # Rule 3. Sent, but not known to have landed. Not a success.
        L.settle(conn, trade_id, total_spend, now=clock())
        L.transition(conn, trade_id, L.FAILED, now=clock(),
                     source_tx_hash=outcome.tx_hash,
                     failure_reason=(outcome.error or
                                     'the swap was sent but never confirmed')[:500],
                     needs_investigation=1)
        return ExecutionResult(trade_id=trade_id, state=L.FAILED, created=True,
                               tx_hash=outcome.tx_hash,
                               failure_reason=(outcome.error or
                                               'the swap was sent but never confirmed'),
                               needs_investigation=True, warnings=warnings)

    L.transition(conn, trade_id, L.CONFIRMING, now=clock(),
                 source_tx_hash=outcome.tx_hash)

    # ── the fee, after the swap is real ──
    fee = FeeOutcome(charged=True, usd=plan.fee_usd) if fee_charger is None else \
        _charge_safely(fee_charger, plan, outcome)
    if not (fee.charged or fee.pending):
        # The swap happened. The fee did not. That is a debt, recorded as
        # such -- never a reason to unwind or repeat a confirmed swap.
        warnings.append(f'the platform fee was not collected: {fee.error}')

    actual_spend = (_d(outcome.actual_spend_usd)
                    if outcome.actual_spend_usd is not None else total_spend)
    if actual_spend > total_spend:
        # Coming in over the quote is the failure the ceiling exists to
        # prevent, so it is surfaced rather than absorbed into the total.
        warnings.append(f'the trade cost ${actual_spend}, above the ${total_spend} quoted')

    L.record_costs(conn, trade_id, 'actual',
                   _actual_cost_lines(plan, outcome, fee), now=clock())

    # The sponsor fronted gas; the user's budget paid for it. Recorded so
    # the subsidy counter can see it come back.
    if outcome.gas_sponsorship_id:
        try:
            S.attach_to_trade(conn, outcome.gas_sponsorship_id, trade_id, plan.gas_usd)
        except S.SubsidyError as e:
            warnings.append(f'gas grant could not be attached to this trade: {e}')

    L.settle(conn, trade_id, actual_spend, now=clock())
    unresolved_fee = not (fee.charged or fee.pending)
    L.transition(conn, trade_id, L.COMPLETED, now=clock(),
                 actual_spend_usd=str(actual_spend), actual_subsidy_usd='0',
                 needs_investigation=1 if unresolved_fee else 0)
    return ExecutionResult(trade_id=trade_id, state=L.COMPLETED, created=True,
                           tx_hash=outcome.tx_hash, actual_spend_usd=str(actual_spend),
                           needs_investigation=unresolved_fee, warnings=warnings)


def _charge_safely(fee_charger, plan, outcome) -> FeeOutcome:
    try:
        return fee_charger(plan, outcome)
    except Exception as e:
        return FeeOutcome(charged=False, error=str(e))


def _minimum_output(quote_row: dict) -> int:
    import json
    body = json.loads(quote_row['breakdown_json'])
    try:
        return int(body.get('minimum_output_raw') or 0)
    except (TypeError, ValueError):
        return 0


def _cost_lines_from(quote_row: dict) -> list:
    import json
    body = json.loads(quote_row['breakdown_json'])
    # CostLine rather than a local struct: it refuses floats, refuses a
    # negative cost and validates the payer, and a cost line that reaches the
    # ledger unvalidated is how a wrong figure becomes history.
    return [CostLine(c['kind'], _d(c['usd']), c.get('payer', 'user'),
                     c.get('source', 'quote'), bool(c.get('sponsored')), c.get('detail', ''))
            for c in (body.get('costs') or [])]


def _actual_cost_lines(plan: SwapPlan, outcome: SwapOutcome, fee: FeeOutcome) -> list:
    """What was really paid, kind by kind.

    The slippage reserve is deliberately absent: it was a reserve, not a
    charge, and writing it as an actual cost would report money as spent
    that was only ever held back.
    """
    lines = []
    gas = outcome.actual_gas_usd if outcome.actual_gas_usd is not None else plan.gas_usd
    if _d(gas) > 0:
        lines.append(CostLine(KIND_SOURCE_GAS, _d(gas), PAYER_USER, 'chain',
                              bool(outcome.gas_sponsorship_id),
                              'fronted by sponsor, charged to the user'
                              if outcome.gas_sponsorship_id else ''))
    # A pending fee carries its amount: the user's budget did pay it, which is
    # what this line records. Whether OrcAgent's transfer landed is a
    # collection question, tracked where collections are tracked.
    if fee.charged or fee.pending:
        lines.append(CostLine(KIND_PLATFORM_FEE, _d(fee.usd), PAYER_USER, 'orcagent', False,
                              '' if fee.charged else 'dispatched; collection recorded separately'))
    else:
        lines.append(CostLine(KIND_PLATFORM_FEE, _d(0), PAYER_USER, 'orcagent', False,
                              f'NOT COLLECTED: {fee.error}'))
    return lines


# ── cleaning up after a crash ────────────────────────────────────────────
def reap_stale_reservations(conn, older_than_seconds: float = 900,
                            now: Optional[float] = None) -> list:
    """Release claims left behind by a process that died before executing.

    Only for trades that never reached EXECUTING. A trade that was executing
    when the process died may have money in flight, and releasing its claim
    would let the next trade spend that money a second time -- so those are
    left held for a human, which is the whole reason this is not a blanket
    timeout.
    """
    ts = now if now is not None else time.time()
    cutoff = ts - older_than_seconds
    rows = conn.execute(
        "SELECT r.trade_id FROM balance_reservations r "
        "JOIN trade_executions e ON e.trade_id = r.trade_id "
        "WHERE r.status='held' AND r.created_at < ? AND e.state IN (?,?,?,?)",
        (cutoff, L.CREATED, L.QUOTED, L.ROUTE_SELECTED, L.RESERVED)).fetchall()
    freed = []
    for (trade_id,) in rows:
        try:
            L.release(conn, trade_id, now=ts)
            L.transition(conn, trade_id, L.FAILED, now=ts,
                         failure_reason='abandoned before execution; claim released')
            freed.append(trade_id)
        except (L.LedgerError, L.IllegalTransition):
            continue
    return freed


# ═════════════════════════════════════════════════════════════════════════
#  CROSS-CHAIN
# ═════════════════════════════════════════════════════════════════════════
# A same-chain trade is a function call: it starts, it ends, and the caller
# waits. A cross-chain trade cannot be, because a bridge takes minutes and
# the process that started it may not be the process that finishes it. So it
# is split in two: start_crosschain_trade() runs as far as the origin
# transaction and then STOPS, holding the reservation; resume_crosschain_trade()
# picks it up from whatever state the database says it is in, as many times
# as it takes, from any process.
#
# THE RULE THAT SHAPES ALL OF IT
# A restart is not information. It says nothing about where the money is, so
# it is never a reason to release a claim, and never a reason to resend
# anything. Every state below is designed so that the answer to "may I send
# this?" comes from the database and not from what this process remembers.

@dataclass(frozen=True, kw_only=True)
class SourceOutcome:
    """What happened to the ORIGIN leg of a bridge.

    The three cases are the same three the swap executor has, and for the
    same reason -- a transaction that may or may not have been broadcast is
    its own outcome, not a rounding of the other two.
    """
    submitted: bool
    tx_hash: str = ''
    error: str = ''
    # True when the sender cannot rule out that something went out. Keeps the
    # claim and asks a person, rather than releasing money that may be in
    # flight.
    unknown: bool = False


@dataclass(frozen=True, kw_only=True)
class CrossChainProgress:
    """Where a cross-chain trade is, in terms a caller can show a user."""
    trade_id: str
    state: str
    created: bool = False
    provider_status: str = ''
    source_tx_hash: str = ''
    destination_tx_hash: str = ''
    swap_tx_hash: str = ''
    actual_spend_usd: str = ''
    failure_reason: str = ''
    needs_investigation: bool = False
    warnings: list = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.state in L.TERMINAL

    def to_dict(self) -> dict:
        return {
            'trade_id': self.trade_id, 'state': self.state,
            'created': self.created, 'provider_status': self.provider_status,
            'source_tx_hash': self.source_tx_hash,
            'destination_tx_hash': self.destination_tx_hash,
            'swap_tx_hash': self.swap_tx_hash,
            'actual_spend_usd': self.actual_spend_usd,
            'failure_reason': self.failure_reason,
            'needs_investigation': self.needs_investigation,
            'warnings': list(self.warnings),
            'completed': self.state == L.COMPLETED,
            'finished': self.finished,
        }


def _progress(conn, trade_id: str, *, created: bool = False,
              warnings: Optional[list] = None) -> CrossChainProgress:
    """Read the trade back out rather than reporting what we think we set."""
    trade = L.get_trade(conn, trade_id) or {}
    cc = L.get_crosschain(conn, trade_id) or {}
    return CrossChainProgress(
        trade_id=trade_id, state=trade.get('state', L.CREATED), created=created,
        provider_status=cc.get('provider_status', '') or '',
        source_tx_hash=cc.get('source_tx_hash', '') or trade.get('source_tx_hash', '') or '',
        destination_tx_hash=cc.get('destination_tx_hash', '') or '',
        swap_tx_hash=cc.get('swap_tx_hash', '') or '',
        actual_spend_usd=trade.get('actual_spend_usd', '') or '',
        failure_reason=trade.get('failure_reason', '') or '',
        needs_investigation=bool(trade.get('needs_investigation')),
        warnings=list(warnings or []),
    )


def start_crosschain_trade(conn, *, quote_id: str, idempotency_key: str,
                           available_usd, route, source_sender: Callable,
                           clock: Callable = time.time) -> CrossChainProgress:
    """Reserve, open the cross-chain leg, and broadcast the origin transaction.

    Returns with the trade in BRIDGING and the reservation STILL HELD. It is
    not finished and does not pretend to be; resume_crosschain_trade() takes
    it from there.

    `available_usd` is the balance on the SOURCE chain -- not the
    destination, which is where a same-chain trade reserves. Getting that
    backwards would claim against a balance the trade never touches and
    leave the one it does spend unprotected.
    """
    quote_row = L.load_quote(conn, quote_id)
    usable, why = L.quote_is_usable(quote_row, now=clock())
    if not usable:
        raise QuoteNotUsable(why)
    if quote_row['same_chain']:
        raise ExecutionError(
            'this quote is same-chain — it has no bridge to start, and routing it '
            'here would record a journey it never took')

    trade_id, created = L.start_execution(
        conn, idempotency_key=idempotency_key, quote_row=quote_row, now=clock())
    if not created:
        # An identical request owns this trade. Whatever it has done, it did
        # once; report it and send nothing.
        return _progress(conn, trade_id, created=False, warnings=[
            'This trade was already started by an identical request; nothing was '
            'sent a second time.'])

    source_chain = quote_row['source_chain']
    total_spend = _d(quote_row['total_cost_usd'])
    warnings: list = []

    def fail(reason: str, *, investigate: bool = False, release: bool = True,
             state: str = L.FAILED):
        if release:
            try:
                L.release(conn, trade_id, now=clock())
            except L.LedgerError:
                pass
        L.transition(conn, trade_id, state, now=clock(),
                     failure_reason=reason[:500],
                     needs_investigation=1 if investigate else 0)
        return _progress(conn, trade_id, created=True, warnings=warnings)

    L.transition(conn, trade_id, L.QUOTED, now=clock())
    L.record_costs(conn, trade_id, 'quoted', _cost_lines_from(quote_row), now=clock())
    L.transition(conn, trade_id, L.ROUTE_SELECTED, now=clock())

    try:
        L.reserve(conn, user_id=quote_row['user_id'], chain=source_chain,
                  trade_id=trade_id, amount_usd=total_spend,
                  available_usd=_d(available_usd), now=clock())
    except L.InsufficientAvailable as e:
        return fail(str(e), release=False)
    L.transition(conn, trade_id, L.RESERVED, now=clock())
    L.transition(conn, trade_id, L.EXECUTING, now=clock())

    # The row is the permission to broadcast. Opening it is what makes a
    # second attempt impossible: the PRIMARY KEY collides in the database,
    # where two concurrent callers cannot both win, rather than in a SELECT
    # both of them could pass.
    opened = L.open_crosschain(
        conn, trade_id=trade_id, quote_id=quote_id, user_id=quote_row['user_id'],
        provider=route.provider, source_chain=source_chain,
        destination_chain=quote_row['destination_chain'],
        source_token=route.source_token, destination_token=route.destination_token,
        source_amount_raw=route.source_amount_raw, now=clock(),
        provider_quote_id=route.quote_id, provider_zid=route.zid,
        quoted_out_raw=str(route.expected_out_raw),
        minimum_out_raw=str(route.minimum_out_raw),
        estimated_seconds=int(route.estimated_seconds or 0),
        estimated_fees_json=json.dumps(route.fees_raw or {})[:4000])
    if not opened:
        return fail('a cross-chain leg is already open for this trade — refusing to '
                    'start a second bridge', investigate=True, release=False,
                    state=L.MANUAL_REVIEW)

    L.transition(conn, trade_id, L.AWAITING_SOURCE, now=clock())

    try:
        outcome = source_sender(route)
    except Exception as e:
        # A sender that raised may still have broadcast. The claim stays and
        # a person looks; releasing here is how a bridged balance gets spent
        # a second time.
        L.update_crosschain(conn, trade_id, failure_reason=f'sender raised: {e}'[:500],
                            now=clock())
        return fail(f'the origin transaction may have been sent: {e}',
                    investigate=True, release=False, state=L.MANUAL_REVIEW)

    if outcome.tx_hash:
        L.update_crosschain(conn, trade_id, source_tx_hash=outcome.tx_hash,
                            source_sent_at=clock(), now=clock())

    if not outcome.submitted:
        if outcome.unknown:
            L.update_crosschain(conn, trade_id,
                                failure_reason=(outcome.error or 'unknown')[:500],
                                now=clock())
            return fail(outcome.error or 'the origin transaction may have been sent '
                        'but could not be confirmed', investigate=True, release=False,
                        state=L.MANUAL_REVIEW)
        return fail(outcome.error or 'the origin transaction was not sent')

    L.transition(conn, trade_id, L.BRIDGING, now=clock(),
                 source_tx_hash=outcome.tx_hash)
    L.update_crosschain(conn, trade_id, provider_status='origin_tx_pending', now=clock())
    return _progress(conn, trade_id, created=True, warnings=warnings)


def resume_crosschain_trade(conn, *, trade_id: str, status_fetcher: Callable,
                            dest_swap_executor: Callable,
                            fee_charger: Optional[Callable] = None,
                            deadline_seconds: float = 3600.0,
                            clock: Callable = time.time) -> CrossChainProgress:
    """Move one cross-chain trade as far forward as its real state allows.

    Safe to call repeatedly, from any process, at any time. Every branch
    decides what to do from the persisted state, so calling it twice cannot
    bridge twice or swap twice -- and calling it after a restart is the
    ordinary case, not a special one.
    """
    trade = L.get_trade(conn, trade_id)
    cc = L.get_crosschain(conn, trade_id)
    if not trade or not cc:
        raise ExecutionError(f'{trade_id} is not a cross-chain trade')
    state = trade['state']
    if state in L.TERMINAL:
        return _progress(conn, trade_id)

    warnings: list = []

    def fail(reason: str, *, investigate: bool = False, release: bool = True,
             to: str = L.FAILED):
        if release:
            try:
                L.release(conn, trade_id, now=clock())
            except L.LedgerError:
                pass
        L.update_crosschain(conn, trade_id, failure_reason=reason[:500], now=clock())
        L.transition(conn, trade_id, to, now=clock(), failure_reason=reason[:500],
                     needs_investigation=1 if investigate else 0)
        return _progress(conn, trade_id, warnings=warnings)

    # ── AWAITING_SOURCE: did anything go out? ────────────────────────────
    #
    # THE CRASH WINDOW, DOCUMENTED PRECISELY
    # Between these two lines in the sender:
    #
    #     tx_hash = <sign and broadcast>          <-- money may now be in flight
    #     L.update_crosschain(..., source_tx_hash=tx_hash)
    #
    # a process death leaves an origin transaction on chain that this database
    # has never heard of. The window is milliseconds wide and it cannot be
    # closed by ordering alone: something has to be written before the send,
    # and whatever is written must identify the transaction that the send then
    # produces.
    #
    # WHY IT IS NOT CLOSED HERE, for each chain:
    #
    #   EVM. A transaction's hash is knowable before broadcast -- it is the
    #   hash of the signed bytes -- so the bytes could be persisted first and
    #   the chain queried afterwards. That is genuinely recoverable and is the
    #   right fix. It is not done yet because it means restructuring the
    #   signer to separate signing from sending, and doing that badly is worse
    #   than the window it closes. Recording the NONCE alone is not enough: a
    #   nonce tells you whether the account has moved past it, not whether the
    #   transaction that moved it was ours.
    #
    #   Solana. A transaction's signature is the first signature in the signed
    #   message, so it too is knowable before send. Same conclusion, same
    #   reason.
    #
    # WHAT IS NOT DONE, deliberately: no scanning of recent blocks for
    # something that looks like ours, and no rebroadcast. Both are heuristics
    # about money, and the failure mode of a wrong guess here is bridging a
    # user's balance twice.
    #
    # So the window stays, it is narrow, and landing in it costs a person's
    # attention rather than a user's money.
    if state == L.AWAITING_SOURCE:
        if not cc.get('source_tx_hash'):
            # No hash was ever written. Either the send never happened or the
            # process died between broadcasting and recording it -- and those
            # are indistinguishable from here. Retrying risks a second bridge
            # of the user's money, so it is not retried.
            return fail('the process stopped while sending the origin transaction, '
                        'and whether it was broadcast cannot be established from '
                        'here — resolving this needs a person, not a retry',
                        investigate=True, release=False, to=L.MANUAL_REVIEW)
        L.transition(conn, trade_id, L.BRIDGING, now=clock(),
                     source_tx_hash=cc['source_tx_hash'])
        state = L.BRIDGING
        trade = L.get_trade(conn, trade_id)

    # ── BRIDGING: ask the provider ───────────────────────────────────────
    if state == L.BRIDGING:
        try:
            # The quote id is passed when there is one. Rows written before
            # quoteId and zid were told apart have only the old route_id, and
            # that one is NOT passed: it may hold a zid, and sending a request
            # id where a quote id is expected is the confusion this split
            # exists to end. Those rows fall back to the two-parameter lookup,
            # which is the shape 0x's own example uses.
            status = status_fetcher(cc['source_chain'], cc['source_tx_hash'],
                                    cc.get('provider_quote_id') or '')
        except Exception as e:
            # Not being able to ask is not news about the money. Stay put.
            warnings.append(f'status unavailable: {e}')
            L.update_crosschain(conn, trade_id,
                                poll_attempts=int(cc.get('poll_attempts') or 0) + 1,
                                now=clock())
            return _progress(conn, trade_id, warnings=warnings)

        L.update_crosschain(
            conn, trade_id, provider_status=status.status,
            poll_attempts=int(cc.get('poll_attempts') or 0) + 1,
            destination_tx_hash=status.destination_tx_hash or cc.get('destination_tx_hash', ''),
            bridge_tx_hash=status.bridge_tx_hash or cc.get('bridge_tx_hash', ''),
            actual_out_raw=(str(status.settled_out_raw)
                            if status.settled_out_raw is not None
                            else cc.get('actual_out_raw', '')),
            now=clock())

        if status.status == 'origin_tx_reverted':
            # The origin transaction landed and did nothing. The USDC never
            # left the source chain, so the whole claim goes back.
            return fail(status.failure_reason or
                        'the origin transaction reverted — nothing left the source chain')
        if status.status == 'bridge_failed':
            # The origin leg succeeded and the delivery did not. The money is
            # somewhere in the provider's hands and is owed back; that is a
            # refund, not a failure to forget about.
            L.update_crosschain(conn, trade_id,
                                failure_reason=(status.failure_reason or 'bridge failed')[:500],
                                now=clock())
            L.transition(conn, trade_id, L.REFUND_PENDING, now=clock(),
                         failure_reason=(status.failure_reason or 'bridge failed')[:500],
                         needs_investigation=1)
            return _progress(conn, trade_id, warnings=warnings)
        if status.filled:
            L.transition(conn, trade_id, L.DEST_RECEIVED, now=clock(),
                         destination_tx_hash=status.destination_tx_hash or '')
            state = L.DEST_RECEIVED
            cc = L.get_crosschain(conn, trade_id)
        else:
            sent_at = float(cc.get('source_sent_at') or 0)
            if sent_at and (clock() - sent_at) > deadline_seconds:
                # Measured from the broadcast, not from process start, so a
                # restart does not hand a stuck bridge a fresh hour.
                return fail(
                    f'the bridge has not settled {int(clock() - sent_at)}s after the '
                    f'origin transaction — the money is on chain somewhere and a '
                    f'person needs to find it', investigate=True, release=False,
                    to=L.MANUAL_REVIEW)
            return _progress(conn, trade_id, warnings=warnings)

    # ── DEST_RECEIVED: buy the token ─────────────────────────────────────
    if state == L.DEST_RECEIVED:
        # THE SECOND-SWAP INVARIANT, checked once more before acting on it.
        #
        # This engine's division of labour is: the bridge delivers the
        # destination chain's DOLLAR asset, and OrcAgent's own swap then buys
        # the token. The swap below therefore spends the destination stable.
        # If the bridge delivered anything else -- most dangerously the final
        # token itself, if a route were ever quoted that ends in it -- then
        # running the swap would either spend an asset that is not there or
        # sell the very token the user just received.
        #
        # verify_route refuses such a route at quote time. This checks the
        # PERSISTED row as well, because the row is what a restart acts on and
        # it may predate that check.
        dest_cfg = _registry.get_chain(cc['destination_chain'])
        if (cc['destination_token'] or '').strip().lower() != \
                dest_cfg.stable.address.lower():
            return fail(
                f'the bridge was recorded as delivering {cc["destination_token"]} on '
                f'{cc["destination_chain"]}, not that chain\'s {dest_cfg.stable.symbol}. '
                f'Refusing to run a destination swap against an asset this trade did '
                f'not bridge into', investigate=True, release=False, to=L.MANUAL_REVIEW)
        quote_row = L.load_quote(conn, cc['quote_id']) or {}
        costs = _quoted_costs(quote_row)
        plan = SwapPlan(
            trade_id=trade_id, user_id=trade['user_id'], wallet=trade['wallet'],
            chain=cc['destination_chain'], token_address=quote_row['token_address'],
            purchase_usd=_d(quote_row['token_purchase_usd']),
            max_spend_usd=_d(quote_row['max_spend_usd']),
            fee_usd=costs.get('platform_fee', _d(0)),
            gas_usd=costs.get('destination_gas', costs.get('source_gas', _d(0))),
            minimum_output_raw=_minimum_output(quote_row),
            mode=quote_row['mode'], same_chain=False,
        )

        # WHAT ARRIVED HAS TO COVER WHAT THIS SWAP WILL SPEND.
        #
        # It does, by construction: the bridge fee on the quote is computed
        # from the GUARANTEED minimum (CrossChainRoute.loss_raw uses
        # minimum_out_raw) and rounded up, so the purchase is the remainder of
        # a ceiling that already assumed the worst delivery. On the live $30
        # route that is $29.44 of spending against $29.446652 guaranteed.
        #
        # Which means a shortfall here is not a rounding question -- it is the
        # bridge delivering less than it promised, or a quote priced off the
        # EXPECTED amount instead of the minimum. Either way the right answer
        # is to stop and say so: sending a swap for dollars that are not there
        # fails on the far side with somebody else's error message, and the
        # user is left reading it.
        delivered_raw = int(str(cc.get('actual_out_raw') or 0) or 0)
        if delivered_raw > 0:
            scale = Decimal(10) ** dest_cfg.stable.require_decimals()
            delivered_usd = Decimal(delivered_raw) / scale
            # Gas on the destination chain is paid in its native token, not in
            # the dollars the bridge delivered, so only these two count.
            needed_usd = plan.purchase_usd + plan.fee_usd
            if delivered_usd < needed_usd:
                return fail(
                    f'the bridge delivered {delivered_usd} on '
                    f'{cc["destination_chain"]} and this trade is about to spend '
                    f'{needed_usd} there. The quote guaranteed at least '
                    f'{Decimal(int(cc.get("minimum_out_raw") or 0)) / scale}, so '
                    f'something under-delivered — refusing to swap dollars that '
                    f'are not there', investigate=True, release=False,
                    to=L.MANUAL_REVIEW)

        L.transition(conn, trade_id, L.SWAPPING, now=clock())
        try:
            outcome = dest_swap_executor(plan)
        except Exception as e:
            return fail(f'the destination swap may have been sent: {e}',
                        investigate=True, release=False, to=L.MANUAL_REVIEW)
        if not outcome.submitted:
            # The bridge worked and the swap did not. The user holds USDC on
            # the destination chain -- that is not the token they wanted, but
            # it is their money and it is safe, so the claim is released.
            return fail(outcome.error or 'the destination swap was not sent')
        L.update_crosschain(conn, trade_id, swap_tx_hash=outcome.tx_hash, now=clock())
        if outcome.reverted:
            gas = (_d(outcome.actual_gas_usd) if outcome.actual_gas_usd is not None
                   else plan.gas_usd)
            L.settle(conn, trade_id, gas, now=clock())
            L.transition(conn, trade_id, L.FAILED, now=clock(),
                         destination_tx_hash=outcome.tx_hash,
                         failure_reason=(outcome.error or
                                         'the destination swap reverted')[:500])
            return _progress(conn, trade_id, warnings=warnings)
        if not outcome.confirmed:
            L.settle(conn, trade_id, _d(quote_row['total_cost_usd']), now=clock())
            L.transition(conn, trade_id, L.MANUAL_REVIEW, now=clock(),
                         destination_tx_hash=outcome.tx_hash,
                         failure_reason=(outcome.error or 'the destination swap was '
                                         'sent but never confirmed')[:500],
                         needs_investigation=1)
            return _progress(conn, trade_id, warnings=warnings)

        L.transition(conn, trade_id, L.CONFIRMING, now=clock(),
                     destination_tx_hash=outcome.tx_hash)
        fee = (FeeOutcome(charged=True, usd=plan.fee_usd) if fee_charger is None
               else _charge_safely(fee_charger, plan, outcome))
        if not (fee.charged or fee.pending):
            warnings.append(f'the platform fee was not collected: {fee.error}')

        total_spend = _d(quote_row['total_cost_usd'])
        actual = (_d(outcome.actual_spend_usd)
                  if outcome.actual_spend_usd is not None else total_spend)
        if actual > total_spend:
            # Rule 9, at the only point where it can still be checked. The
            # ceiling cannot be enforced retroactively on money already
            # spent, so it is reported rather than quietly absorbed.
            warnings.append(f'the trade cost ${actual}, above the ${total_spend} quoted')
        L.record_costs(conn, trade_id, 'actual',
                       _actual_cost_lines(plan, outcome, fee), now=clock())
        L.settle(conn, trade_id, actual, now=clock())
        unresolved_fee = not (fee.charged or fee.pending)
        L.transition(conn, trade_id, L.COMPLETED, now=clock(),
                     actual_spend_usd=str(actual), actual_subsidy_usd='0',
                     needs_investigation=1 if unresolved_fee else 0)
        return _progress(conn, trade_id, warnings=warnings)

    # ── SWAPPING / CONFIRMING: a crash mid-swap ──────────────────────────
    if state in (L.SWAPPING, L.CONFIRMING):
        if cc.get('swap_tx_hash'):
            if state == L.SWAPPING:
                L.transition(conn, trade_id, L.CONFIRMING, now=clock(),
                             destination_tx_hash=cc['swap_tx_hash'])
            # A confirmed fill cannot be established from here without the
            # chain, and guessing it completes a trade that may not exist.
            return fail('the destination swap was sent and this process cannot '
                        'establish whether it filled', investigate=True,
                        release=False, to=L.MANUAL_REVIEW)
        return fail('the process stopped while swapping on the destination chain, '
                    'and whether anything was sent cannot be established from here',
                    investigate=True, release=False, to=L.MANUAL_REVIEW)

    # ── REFUND_PENDING: has the money come back? ─────────────────────────
    if state == L.REFUND_PENDING:
        try:
            status = status_fetcher(cc['source_chain'], cc['source_tx_hash'],
                                    cc.get('provider_quote_id') or '')
        except Exception as e:
            warnings.append(f'status unavailable: {e}')
            return _progress(conn, trade_id, warnings=warnings)
        L.update_crosschain(conn, trade_id, provider_status=status.status, now=clock())
        refunded = bool((status.recovery or {}).get('refunded')
                        or (status.recovery or {}).get('refundTxHash'))
        if refunded:
            # The user has their USDC back on the source chain, minus the gas
            # that was genuinely spent getting there. Only that is settled.
            quote_row = L.load_quote(conn, cc['quote_id']) or {}
            gas = _quoted_costs(quote_row).get('source_gas', _d(0))
            L.settle(conn, trade_id, gas, now=clock())
            L.transition(conn, trade_id, L.REFUNDED, now=clock(),
                         failure_reason='the bridge failed and the funds were refunded')
            return _progress(conn, trade_id, warnings=warnings)
        return _progress(conn, trade_id, warnings=warnings)

    return _progress(conn, trade_id, warnings=warnings)
