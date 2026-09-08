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

import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Optional

from . import ledger as L
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


@dataclass(frozen=True)
class SwapOutcome:
    """What actually happened on-chain.

    `submitted` and `confirmed` are separate on purpose. An executor that
    cannot tell the difference must report submitted=True, confirmed=False
    -- which is treated as money possibly gone, not as a success and not as
    a clean failure.
    """
    submitted: bool
    confirmed: bool
    tx_hash: str = ''
    actual_spend_usd: Optional[Decimal] = None
    actual_gas_usd: Optional[Decimal] = None
    gas_sponsorship_id: Optional[int] = None
    error: str = ''


@dataclass(frozen=True)
class FeeOutcome:
    charged: bool
    usd: Decimal = Decimal('0')
    tx_hash: str = ''
    error: str = ''


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
    if not fee.charged:
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
    L.transition(conn, trade_id, L.COMPLETED, now=clock(),
                 actual_spend_usd=str(actual_spend), actual_subsidy_usd='0',
                 needs_investigation=1 if not fee.charged else 0)
    return ExecutionResult(trade_id=trade_id, state=L.COMPLETED, created=True,
                           tx_hash=outcome.tx_hash, actual_spend_usd=str(actual_spend),
                           needs_investigation=not fee.charged, warnings=warnings)


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
    lines.append(CostLine(KIND_PLATFORM_FEE, _d(fee.usd) if fee.charged else _d(0),
                          PAYER_USER, 'orcagent', False,
                          '' if fee.charged else f'NOT COLLECTED: {fee.error}'))
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
