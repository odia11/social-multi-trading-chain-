"""Side-effect-free regression coverage for EVM exits with zero native gas."""
import os
import sys
import types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bsc_gasless_trading as gasless


class Chain:
    kind = 'evm'
    chain_id = 8453
    display_name = 'Base'
    native = types.SimpleNamespace(symbol='ETH')
    stable = types.SimpleNamespace(
        symbol='USDC',
        address='0x' + '2' * 40,
        decimals=6,
    )


class Registry:
    def get_chain(self, name):
        assert name == 'base'
        return Chain()


def dashboard():
    d = types.SimpleNamespace()
    d.te_registry = Registry()
    d.FEE_RATE_TXN = 0.0075
    d.GAS_TOPUP_USDC_AMOUNT = 2.0
    d._redact_keys = lambda x: str(x)
    d._evm_fee_recipient = lambda chain: '0x' + '3' * 40
    d.ZEROX_API_KEY = 'test-key'
    d.get_evm_usdc_balance = lambda addr, chain: 25.0
    calls = {'execute': [], 'ensure': [], 'fee': []}

    def original_execute(wallet, key, action, token, amount, chain='bsc'):
        calls['execute'].append((wallet, action, token, amount, chain))
        return True, '', '0xlegacy'

    def original_ensure(*args, **kwargs):
        calls['ensure'].append((args, kwargs))
        return False, 'legacy gas gate', None

    def original_fee(*args, **kwargs):
        calls['fee'].append((args, kwargs))

    d._execute_evm_swap = original_execute
    d._ensure_evm_gas = original_ensure
    d._charge_evm_txn_fee = original_fee
    return d, calls


def test_sell_context_reaches_relayer_before_native_gas_gate():
    d, calls = dashboard()
    gasless.install(d)

    def _evm_sell_flow():
        return d._ensure_evm_gas(
            7, 'wallet', 'key', '0x' + '4' * 40, 'base')

    assert _evm_sell_flow() == (True, '', None)
    assert calls['ensure'] == []


def test_gasless_sell_is_first_choice():
    d, calls = dashboard()
    old_quote, old_submit = gasless._gasless_sell_quote, gasless._submit_and_wait
    try:
        gasless._gasless_sell_quote = lambda *a, **k: ({'trade': {}}, Chain())
        gasless._submit_and_wait = lambda *a, **k: '0xgaslesssell'
        gasless.install(d)
        result = d._execute_evm_swap(
            'wallet', 'key', 'sell', '0x' + '5' * 40, '12.5', 'base')
        assert result == (True, '', '0xgaslesssell')
        assert calls['execute'] == []
    finally:
        gasless._gasless_sell_quote, gasless._submit_and_wait = old_quote, old_submit


def test_nonpermit_token_uses_user_stablecoin_for_gas_then_legacy_sell():
    d, calls = dashboard()
    old_quote = gasless._gasless_sell_quote
    old_topup = gasless._gasless_native_topup
    topups = []
    try:
        def fail_quote(*a, **k):
            raise RuntimeError('gasless approval unavailable')
        gasless._gasless_sell_quote = fail_quote
        gasless._gasless_native_topup = lambda *a, **k: topups.append('user-funded') or '0xtopup'
        gasless.install(d)
        result = d._execute_evm_swap(
            'wallet', 'key', 'sell', '0x' + '6' * 40, '3', 'base')
        assert result == (True, '', '0xlegacy')
        assert topups == ['user-funded']
        assert len(calls['execute']) == 1
        assert calls['execute'][0][1] == 'sell'
    finally:
        gasless._gasless_sell_quote = old_quote
        gasless._gasless_native_topup = old_topup


def test_topup_quote_has_no_orcagent_platform_fee():
    src = open('bsc_gasless_trading.py', encoding='utf-8').read()
    block = src[src.index('def _gasless_native_topup'):src.index('def _submit_and_wait')]
    assert "'buyToken': '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'" in block
    assert 'swapFeeBps' not in block
    assert 'swapFeeRecipient' not in block


def test_sell_quote_collects_fee_in_stable_proceeds():
    src = open('bsc_gasless_trading.py', encoding='utf-8').read()
    block = src[src.index('def _gasless_sell_quote'):src.index('def _gasless_native_topup')]
    assert "'buyToken': chain.stable.address" in block
    assert "'swapFeeToken': chain.stable.address" in block
    assert "'swapFeeBps': str(fee_bps)" in block


if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL GASLESS SELL REGRESSIONS PASSED')
