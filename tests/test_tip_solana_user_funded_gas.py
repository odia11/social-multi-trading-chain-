"""Regression guards for user-funded Solana tip gas bootstrap."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TIP=(ROOT/'portfolio_token_withdraw.py').read_text()
BOOT=(ROOT/'solana_source_bridge_gasless.py').read_text()


def block(src,a,b):
    x=src.index(a); y=src.index(b,x); return src[x:y]


def test_generic_solana_topup_is_exposed():
    b=block(BOOT,'def user_funded_solana_topup','def auto_bridge')
    assert "d._gasless_solana_native_topup = user_funded_solana_topup" in b
    assert '_pick_gasless_order' in b
    assert '_execute_order' in b
    assert '_sponsor_solana_gas' not in b
    assert 'GAS_SPONSOR' not in b


def test_tip_preserves_requested_amount_and_only_spends_spare_usdc_for_gas():
    b=block(TIP,"@app.post('/api/tip')","@app.post('/api/wallet/send-token')")
    assert "spare = sol['balance'] - amount" in b
    assert "topup(sender_wallet, spare, target_sol=float(target_sol))" in b
    assert "_solana_transfer(\n                            d, sender_wallet, d.USDC_MINT,\n                            recipient_address, amount)" in b


def test_low_sol_solana_is_still_a_tip_candidate_for_bootstrap():
    b=block(TIP,'def _tip_solana_ready','def _tip_evm_candidates')
    assert "_tip_required_lamports" in b
    assert "'native_ready': lamports >= required_lamports" in b
    assert "Cannot verify the SOL network-fee balance" in b


def test_no_platform_sponsor_in_tip_bootstrap_path():
    b=block(TIP,"@app.post('/api/tip')","@app.post('/api/wallet/send-token')")
    assert '_gasless_solana_native_topup' in b
    assert '_sponsor_solana_gas' not in b
    assert 'GAS_SPONSOR' not in b


def test_native_sol_helper_uses_rpc_fallbacks():
    dash=(ROOT/'dashboard.py').read_text()
    a=dash.index('def _get_user_sol')
    b=dash.index('def get_token_data',a)
    body=dash[a:b]
    assert 'CLAIM_SOL_RPCS' in body
    assert '_PROXY_RPCS' in body
    assert "raise RuntimeError('SOL balance unavailable'" in body


def test_tip_readiness_uses_validated_transfer_sources():
    b=block(TIP,'def _tip_solana_ready','def _tip_evm_candidates')
    assert '_solana_source_accounts(d, owner, str(d.USDC_MINT))' in b
    assert 'Your balance is unknown, not zero' in b


def test_bootstrap_trusts_caller_spare_usdc_when_balance_rpc_is_down():
    b=block(BOOT,'def user_funded_solana_topup','def auto_bridge')
    assert 'except Exception:' in b
    assert 'sol_usdc = max_spend' in b



def test_direct_solana_failure_can_retry_after_user_funded_topup():
    b=block(TIP,"@app.post('/api/tip')","@app.post('/api/wallet/send-token')")
    assert 'isinstance(exc, ValueError)' in b
    assert 'or solana_gas_shortfall' in b
    assert "solana_error = safe[:220]" in b
    assert b.count('_solana_transfer(') >= 2

def test_topup_targets_absolute_required_sol_plus_margin():
    b=block(TIP,"@app.post('/api/tip')","@app.post('/api/wallet/send-token')")
    assert "Decimal(max(required, 0)) / Decimal(1_000_000_000)" in b
    assert "+ Decimal('0.0005')" in b


if __name__=='__main__':
    for n in sorted(x for x in globals() if x.startswith('test_')):
        globals()[n]()
        print('PASS', n)
    print('ALL USER-FUNDED SOLANA TIP GAS REGRESSIONS PASSED')
