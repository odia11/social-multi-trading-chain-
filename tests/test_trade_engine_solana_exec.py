"""Solana execution through the trade engine, and the one guess that must not be wrong.

WHY THIS EXISTS
/api/trade/execute refused every non-EVM chain, so a Solana buy skipped the
three things the engine exists to provide: the ceiling (the typed amount is
the MAXIMUM, costs come out of it), the balance reservation (two trades
cannot claim the same money), and the idempotency key (a retry cannot become
a second swap). The quote side already supported Solana -- JupiterProvider is
wired into _te_swap_provider -- so only execution was missing.

THE HARD PART
_execute_user_swap_ex() returns tx_hash='' for EVERY failure, including a
120-second subprocess timeout. So "no signature" does not mean "nothing was
sent": a swap that really was broadcast and then timed out looks exactly like
one that was never built. The engine's three outcomes hang on telling those
apart, and getting it wrong in the optimistic direction releases a claim on
money that may already be gone -- which lets the next trade spend it twice.

The evidence used instead is orcagent_solana.py's own step output: it prints
a numbered step before each stage and step 5 is the send. These tests pin
that mapping, including the case with no evidence at all, which must be
pessimistic rather than convenient.
"""
import os
import sys
import tempfile
from decimal import Decimal

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp())
os.environ.setdefault('SECRET_KEY', 'x' * 32)
os.environ.setdefault('ENCRYPTION_KEY', 'K' * 43 + '=')
os.environ.setdefault('DEV', '1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard as d                                              # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal


class _Plan:
    """The fields the executor actually reads off a SwapPlan."""
    token_address = 'TokenMint1111111111111111111111111111111111'
    purchase_usd = D('97.90')
    user_id = 1
    chain = 'solana'


class _NullKey:
    """Stands in for _use_key's context manager; hands over a dummy key."""
    def __enter__(self): return 'dummy-private-key'
    def __exit__(self, *a): return False


def run_executor(swap_result, *, gas_ok=True, gas_msg=''):
    """Drive the real executor with a stubbed swap primitive.

    swap_result is (ok, tx_hash, err, token_amt, base_amt, capture_updates).
    """
    ok, tx_hash, err, t_amt, b_amt, cap_updates = swap_result
    seen = {}

    def fake_swap(wallet, pk, action, mint, amount_str, base='SOL', capture=None):
        seen['action'] = action
        seen['amount_str'] = amount_str
        seen['base'] = base
        if capture is not None:
            capture.update(cap_updates)
        return ok, tx_hash, err, t_amt, b_amt

    orig_swap, orig_gas, orig_key = (d._execute_user_swap_ex, d._ensure_solana_gas, d._use_key)
    d._execute_user_swap_ex = fake_swap
    d._ensure_solana_gas = lambda w, pk: (gas_ok, gas_msg)
    d._use_key = lambda blob, w: _NullKey()
    try:
        outcome = d._te_solana_swap_executor('enc', 'Wallet111')(_Plan())
    finally:
        d._execute_user_swap_ex, d._ensure_solana_gas, d._use_key = orig_swap, orig_gas, orig_key
    return outcome, seen


# ── it must sell the PURCHASE, in USDC ────────────────────────────────────
outcome, seen = run_executor((True, 'SIG123', '', 1000.0, 97.9, {'send_attempted': True}))
check('the swap is funded in USDC, not SOL — the whole point of the route',
      seen['base'] == 'USDC')
check('...and sells the PURCHASE the quote settled on, not the ceiling the '
      'user typed', seen['amount_str'] == '97.90')
check('a confirmed swap is reported as submitted and confirmed',
      outcome.submitted and outcome.confirmed and outcome.tx_hash == 'SIG123')


# ── the three failure shapes ──────────────────────────────────────────────
outcome, _ = run_executor((False, '', 'no route found', 0.0, 0.0,
                           {'send_attempted': False, 'onchain_failed': False, 'signature': ''}))
check('a failure that provably never reached the send is NOT submitted, so the '
      'user gets their whole claim back',
      outcome.submitted is False and outcome.confirmed is False)

outcome, _ = run_executor((False, '', 'transaction failed', 0.0, 0.0,
                           {'send_attempted': True, 'onchain_failed': True, 'signature': 'SIGBAD'}))
check('a swap that landed and was rejected on-chain is reverted — it bought '
      'nothing, so only gas actually left the wallet',
      outcome.submitted and outcome.reverted and not outcome.confirmed)
check('...and keeps the signature, so the failure can be looked up',
      outcome.tx_hash == 'SIGBAD')

outcome, _ = run_executor((False, '', 'timed out after 120s', 0.0, 0.0,
                           {'send_attempted': True, 'onchain_failed': False, 'signature': ''}))
check('a swap that was sent and never confirmed is NOT reported as a clean '
      'failure: the money may be gone, so the claim is kept',
      outcome.submitted and not outcome.confirmed and not outcome.reverted)


# ── the case that matters most: no evidence at all ────────────────────────
outcome, _ = run_executor((False, '', 'timed out after 120s', 0.0, 0.0, {}))
check('with NO evidence either way — the subprocess died without usable '
      'output — the pessimistic outcome is assumed. The optimistic guess '
      'releases a claim on money that may already have been spent, which is '
      'how the same balance gets spent twice',
      outcome.submitted and not outcome.confirmed)


# ── the gas refusal is a clean not-sent ───────────────────────────────────
outcome, seen = run_executor((True, 'SIG', '', 0.0, 0.0, {}),
                             gas_ok=False, gas_msg='not enough SOL for network fees')
check('a wallet that cannot pay Solana network fees is refused before the swap '
      'is attempted, and nothing is marked as sent',
      outcome.submitted is False and 'SOL' in outcome.error)
check('...and the swap primitive was never called at all', 'base' not in seen)


# ── the fee rate has to match what is really collected ────────────────────
check('Solana is priced at a zero platform fee, because a USDC-funded buy '
      'collects none — quoting 0.75% would show a cost nobody charges and '
      'shrink the purchase by money that just stays in the wallet',
      d._te_fee_rate_for('solana') == D('0'))
check('...while every EVM chain keeps the real rate, which its separate fee '
      'transfer genuinely does collect',
      d._te_fee_rate_for('base') == D(str(d.FEE_RATE_TXN)) and d.FEE_RATE_TXN > 0)


# ── the flag, and the evidence helper ─────────────────────────────────────
check('Solana execution ships behind a flag that defaults OFF, so the working '
      'legacy route stays in charge until this is watched against real trades',
      d.TRADE_ENGINE_SOLANA is False)

cap = {}
d._capture_broadcast_evidence(cap, '[TRADE] Step 4/8 — Signing transaction\n')
check('evidence: stopping before step 5 reads as never sent',
      cap['send_attempted'] is False)
cap = {}
d._capture_broadcast_evidence(cap, '[TRADE] Step 5/8 — Sending transaction to Solana RPC\n')
check('evidence: reaching step 5 reads as possibly sent', cap['send_attempted'] is True)
cap = {}
d._capture_broadcast_evidence(
    cap, '[TRADE] Step 5 — submitted, NOT yet confirmed: https://solscan.io/tx/ABC123\n')
check('evidence: a signature is recovered even from a run that then failed',
      cap['signature'] == 'ABC123')

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
