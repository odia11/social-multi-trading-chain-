"""Side-effect-free regression guards for integrating GitHub withdraw gas fix.

The remote change added gas funding directly to _solana_transfer, but main
already has a newer gas/rent-aware tip flow. The merged design makes automatic
gas funding opt-in for Portfolio withdrawals and leaves tip routing in charge
of its own gas/bootstrap. Both reserve outgoing USDC before buying SOL gas.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'portfolio_token_withdraw.py').read_text()
BOOT = (ROOT / 'solana_source_bridge_gasless.py').read_text()


def between(a, b):
    i = SRC.index(a)
    j = SRC.index(b, i)
    return SRC[i:j]


def test_portfolio_withdraw_opts_in():
    transfer = between('def _solana_transfer', 'def _evm_transfer')
    withdraw = between("@app.post('/api/wallet/send-token')", "marker = 'data-orca-token-withdraw")
    assert 'allow_user_funded_gas=False' in transfer
    assert 'allow_user_funded_gas=True' in withdraw


def test_tip_owns_its_own_bootstrap_not_double_topup():
    tip = between("@app.post('/api/tip')", "@app.post('/api/wallet/send-token')")
    assert "_gasless_solana_native_topup" in tip
    assert 'allow_user_funded_gas=True' not in tip
    assert 'solana_gas_shortfall' in tip


def test_sol_network_budget_reserves_outgoing_usdc():
    transfer = between('def _solana_transfer', 'def _evm_transfer')
    assert "reserved = amount if token_address == d.USDC_MINT else Decimal('0')" in transfer
    assert 'spare = usdc_balance - reserved' in transfer
    assert "spare < Decimal('0.20')" in transfer
    assert 'topup(wallet, spare, target_sol=float(target_sol))' in transfer
    assert 'GAS_SPONSOR' not in transfer


def test_account_rent_fee_is_part_of_gas_target():
    transfer = between('def _solana_transfer', 'def _evm_transfer')
    assert "getMinimumBalanceForRentExemption" in transfer
    assert "required_lamports + 500_000" in transfer
    assert "lamports < required_lamports" in transfer
    assert "'getBalance'" in transfer
    assert 'SOL top-up was submitted but sufficient gas is not yet confirmed' in transfer


def test_gasless_reuses_user_funded_jupiter_rail():
    assert 'def user_funded_solana_topup' in BOOT
    assert '_pick_gasless_order(' in BOOT
    assert "d._gasless_solana_native_topup = user_funded_solana_topup" in BOOT


if __name__ == '__main__':
    for name in sorted(x for x in globals() if x.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL MERGED TIP/WITHDRAW GAS REGRESSIONS PASSED')
