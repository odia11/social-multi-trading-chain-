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
    assert "topup(sender_wallet, spare, target_sol=0.0025)" in b
    assert "_solana_transfer(\n                            d, sender_wallet, d.USDC_MINT,\n                            recipient_address, amount)" in b


def test_low_sol_solana_is_still_a_tip_candidate_for_bootstrap():
    b=block(TIP,'def _tip_solana_ready','def _tip_evm_candidates')
    assert "'native_ready': lamports >= 10000" in b
    tail=b[b.index('lamports ='):b.index('except Exception:')]
    assert "'native_ready': lamports >= 10000" in tail


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


if __name__=='__main__':
    for n in sorted(x for x in globals() if x.startswith('test_')):
        globals()[n]()
        print('PASS', n)
    print('ALL USER-FUNDED SOLANA TIP GAS REGRESSIONS PASSED')
