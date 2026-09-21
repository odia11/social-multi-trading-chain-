"""Side-effect-free guards for post-bridge EVM budget + position accuracy."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'dashboard.py').read_text()


def block(name, next_marker):
    start = SRC.index('def ' + name)
    return SRC[start:SRC.index(next_marker, start)]


def test_post_bridge_buy_uses_trade_engine_not_direct_swap():
    b = block('_execute_auto_buy_after_bridge(', '\ndef _bridge_sign_send_evm')
    assert '_te_build_and_store_quote(' in b
    assert '_te_run_evm_trade(' in b
    assert '_execute_evm_swap(' not in b
    assert "idem=f'bridge:{bridge_id}:auto-buy'" in b


def test_post_bridge_ceiling_is_never_raised_to_arrived_balance():
    b = block('_execute_auto_buy_after_bridge(', '\ndef _bridge_sign_send_evm')
    assert 'ceiling = min(float(requested_usdc or 0), available)' in b
    assert 'max_spend=Decimal(str(ceiling))' in b
    assert 'max_spend > ceiling + 1e-9' in b


def test_post_bridge_does_not_double_record_fee_or_position():
    b = block('_execute_auto_buy_after_bridge(', '\ndef _bridge_sign_send_evm')
    assert '_record_bundled_stable_fee(' not in b
    assert '_upsert_open_position(' not in b
    # Both responsibilities belong to the one trade-engine execution path.
    assert '_te_run_evm_trade(' in b


def test_trade_engine_measures_real_token_delta():
    b = block('_te_run_evm_trade(', "\n\n@app.route('/api/trade/execute'")
    assert 'balance_before = get_evm_token_balance(' in b
    assert 'balance_after = get_evm_token_balance(' in b
    assert 'received = max(0.0, float(balance_after) - float(balance_before))' in b
    assert "'amount':    received" in b


def test_position_cost_basis_is_actual_purchase_not_ceiling():
    b = block('_te_run_evm_trade(', "\n\n@app.route('/api/trade/execute'")
    assert "purchase = float(quote_row['token_purchase_usd'])" in b
    assert "'spend':     purchase" in b
    assert 'entry_price = (purchase / received)' in b


def test_generic_erc20_balance_uses_contract_decimals():
    b = block('get_evm_token_balance(', '\ndef get_bnb_balance')
    assert 'balanceOf(owner).call()' in b
    assert 'decimals().call()' in b
    assert 'return raw / (10 ** decimals)' in b


if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL POST-BRIDGE BUDGET/POSITION REGRESSIONS PASSED')
