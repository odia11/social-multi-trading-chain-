"""Regression guards for rent-aware tips and Jupiter Ultra gasless buy gates."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIP = (ROOT/'portfolio_token_withdraw.py').read_text()
DASH = (ROOT/'dashboard.py').read_text()
GASLESS = (ROOT/'solana_gasless_trading.py').read_text()


def block(src, a, b):
    x = src.index(a); y = src.index(b, x); return src[x:y]


def test_tip_readiness_includes_recipient_ata_rent():
    b = block(TIP, 'def _tip_required_lamports', 'def _tip_solana_ready')
    assert 'getMinimumBalanceForRentExemption' in b
    assert '[165]' in b
    assert '2_100_000' in b
    assert 'getAccountInfo' in b


def test_tip_native_ready_uses_required_lamports_not_10000():
    b = block(TIP, 'def _tip_solana_ready', 'def _tip_evm_candidates')
    assert '_tip_required_lamports' in b
    assert "'native_ready': lamports >= required_lamports" in b
    assert 'lamports >= 10000' not in b


def test_transfer_enforces_fee_plus_ata_rent_before_send():
    b = block(TIP, 'def _solana_transfer', 'def _evm_transfer')
    assert 'required_lamports = 20_000' in b
    assert 'getMinimumBalanceForRentExemption' in b
    assert 'lamports < required_lamports' in b


def test_ultra_adapter_exposes_configured_capability():
    assert "d._solana_ultra_gasless_configured = bool(_api_key())" in GASLESS


def test_instant_usdc_buy_does_not_require_sol_when_ultra_is_configured():
    # Live market/instant trade occurrence before _solana_buy_flow.
    first = DASH.index('if not _solana_usdc_buy_gasless_enabled():')
    assert 'current_sol < SOL_NETWORK_RESERVE' in DASH[first:first+900]


def test_manual_buy_legacy_sol_gate_is_conditional():
    b = block(DASH, 'def _solana_buy_flow', "@app.route('/api/manual_sell'")
    assert 'if not _solana_usdc_buy_gasless_enabled():' in b
    gate = b.index('if not _solana_usdc_buy_gasless_enabled():')
    assert 'us_sol < SOL_NETWORK_RESERVE' in b[gate:gate+3000]


def test_bot_does_not_skip_gasless_usdc_entries_for_low_sol():
    a = DASH.index('def user_trader_loop')
    b = DASH.index("@app.route('/api/token/", a)
    body = DASH[a:b]
    assert '_gasless_usdc_buy' in body
    assert 'if us_sol < _GAS_MIN and not _gasless_usdc_buy:' in body


if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL SOLANA TIP RENT / GASLESS SWAP REGRESSIONS PASSED')
