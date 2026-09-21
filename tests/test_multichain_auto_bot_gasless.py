"""Regression coverage for Start Trading on USDC-only multi-chain wallets.

The autonomous EVM scanner must not stop before the shared gasless BUY flow just
because BNB/ETH/POL/native gas is zero.  That condition is normal in OrcAgent:
USDC is trading capital and 0x Gasless / the funding flow handles execution.
"""
# Runnable on its own, like every other test here: these import modules from
# the repository root, and `python3 tests/x.py` puts tests/ on the path and
# not the root. Without this the file fails with ModuleNotFoundError and
# reads as a broken test rather than a missing PYTHONPATH.
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import types

import multichain_auto_bot as patch


EVM_CHAINS = ('bsc', 'base', 'arbitrum', 'polygon', 'robinhood')


def make_dashboard(chain):
    calls = []
    original_calls = []

    def old_scanner(*args, **kwargs):
        original_calls.append((args, kwargs))
        return False

    d = types.SimpleNamespace()
    d._bot_scan_evm_entry = old_scanner
    class _KeyCtx:
        def __enter__(self): return '0x' + '1' * 64
        def __exit__(self, *a): return False
    d._use_key = lambda enc, wallet: _KeyCtx()
    class _Acct:
        @staticmethod
        def from_key(key):
            return types.SimpleNamespace(address='0x' + 'b' * 40)
    d._EvmAccount = _Acct
    d.get_evm_native_balance = lambda addr, c: 0.0
    d._get_scanner_cached = lambda: [{
        'chain': chain,
        'mint': '0x' + 'a' * 40,
        'symbol': 'AUTO',
        'market_cap': 1_000_000,
        'liquidity_usd': 250_000,
        'volume_24h': 500_000,
        'pair_created_at': 0,
        'has_profile': True, 'txns24h': 500, 'txns24h_sells': 40,
        'price_change_24h': 30.0,
    }]
    d.get_ai_active_filters = lambda: {
        'min_liquidity_usd': 10_000,
        'min_pair_age_minutes': 0,
    }
    d._min_marketcap_for_stake = lambda amount: 10_000
    d._bot_gainers_eligible = lambda t: (bool(t.get('has_profile'))
        and (t.get('txns24h') or 0) >= 300
        and (t.get('txns24h_sells') or 0) >= 30)
    d.time = types.SimpleNamespace(time=lambda: 1_800_000_000.0)
    d.get_token_data = lambda mint, fast=True, chain=None: {
        'price': 1.0,
        'change5m': 8.0,
        'change1h': 9.0,
        'volume5m': 20_000,
        'volume1h': 100_000,
        'has_profile': True, 'txns24h': 500, 'txns24h_sells': 40,
    }
    d._fast_pump_check = lambda mint, chain=None: False
    d.NO_HONEYPOT_PROVIDER_LIQ_MULT = 5
    d._check_evm_honeypot = lambda mint, c: {
        'ok': True, 'is_honeypot': False, 'sell_tax': 0,
    }
    d.add_user_log = lambda *a, **k: None

    class Resp:
        def get_json(self, silent=True):
            return {'ok': True, 'chain': chain, 'amount_usdc': 10}

    def buy(wallet, data, c, wallet_label='EVM'):
        calls.append((wallet, data, c, wallet_label))
        return Resp()

    d._evm_buy_flow = buy
    return d, calls, original_calls


def test_usdc_only_wallet_reaches_buy_flow_on_every_evm_chain():
    for chain in EVM_CHAINS:
        d, buys, old = make_dashboard(chain)
        patch.install(d)
        ok = d._bot_scan_evm_entry(
            7, 'wallet', {}, chain, 'encrypted', 10.0,
            frozenset(), 5.0, None, True, 'walle...test',
        )
        assert ok is True, chain
        assert old == [], f'{chain}: native-gas legacy gate was reached'
        assert len(buys) == 1, chain
        assert buys[0][2] == chain
        assert buys[0][1]['amount_usdc'] == 10.0


def test_gainers_gate_rejects_missing_metadata_on_every_evm_chain():
    for chain in EVM_CHAINS:
        for field, value in (('has_profile', False), ('txns24h', 299),
                             ('txns24h_sells', 29)):
            d, buys, old = make_dashboard(chain)
            base = d._get_scanner_cached()[0]
            d._get_scanner_cached = lambda base=base, field=field, value=value: [
                {**base, field: value}]
            patch.install(d)
            result = d._bot_scan_evm_entry(
                7, 'wallet', {}, chain, 'encrypted', 10.0,
                frozenset(), 5.0, None, True, 'test')
            assert result is False and not buys, (chain, field)


def test_pending_funding_does_not_queue_duplicate_buys():
    d, buys, _ = make_dashboard('base')
    class Pending:
        def get_json(self, silent=True):
            return {'pending': True, 'ok': False}
    def buy(*args, **kwargs):
        buys.append(args)
        return Pending()
    d._evm_buy_flow = buy
    patch.install(d)
    for _ in range(3):
        d._bot_scan_evm_entry(7, 'wallet', {}, 'base', 'encrypted',
                              10.0, frozenset(), 5.0, None,
                              True, 'test')
    assert len(buys) == 1, 'repeated 2-second cycles must not queue repeated bridge orders'


def test_native_funded_wallet_keeps_mature_existing_scanner():
    d, buys, old = make_dashboard('base')
    d.get_evm_native_balance = lambda addr, chain: 0.01
    patch.install(d)
    d._bot_scan_evm_entry(
        7, 'wallet', {}, 'base', 'encrypted', 10.0,
        frozenset(), 5.0, None, True, 'walle...test',
    )
    assert len(old) == 1
    assert buys == []


def test_production_entry_installs_patch_after_evm_gasless_layer():
    src = open('app_entry.py', encoding='utf-8').read()
    gasless = src.index('_install_evm_gasless_trading(_dashboard)')
    bot = src.index('_install_multichain_auto_bot(_dashboard)')
    assert gasless < bot
