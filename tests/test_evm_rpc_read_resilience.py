"""Regression guards for cached/single-flight EVM balance reads and Base fallback."""
import ast
import concurrent.futures
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'dashboard.py').read_text()
GAS=(ROOT/'gas_manager.py').read_text()


def test_base_has_read_only_fallbacks_and_env_override():
    block=SRC[SRC.index('def _rpc_candidates'):SRC.index('def _web3_for_rpc')]
    assert 'BASE_RPC_FALLBACK_URLS' in block
    assert 'https://public.1rpc.io/base' in block
    assert 'https://base.publicnode.com' in block


def test_transactions_keep_configured_primary_web3():
    block=SRC[SRC.index('def _get_web3'):SRC.index('def _evm_read_with_fallback')]
    assert "EVM_CHAINS[chain]['rpc_url']" in block
    assert '_rpc_candidates' not in block


def test_balance_reads_share_cache_and_fallback_layer():
    native=SRC[SRC.index('def get_evm_native_balance'):SRC.index('def get_evm_usdc_balance')]
    stable=SRC[SRC.index('def get_evm_usdc_balance'):SRC.index('def get_evm_token_balance')]
    assert '_evm_read_with_fallback' in native
    assert '_evm_read_with_fallback' in stable
    assert "('native', chain, addr)" in native
    assert "('stable', chain, addr, token.lower())" in stable


def test_rate_limited_endpoint_enters_cooldown():
    block=SRC[SRC.index('def _evm_read_with_fallback'):SRC.index('# Minimal ERC20/BEP20 ABI')]
    assert "'429' in text" in block
    assert '_EVM_RPC_COOLDOWN_SECONDS' in block
    assert '_evm_rpc_cooldown' in block


def test_balance_cache_is_short_lived():
    assert '_EVM_BALANCE_CACHE_TTL = 3.0' in SRC


def test_gas_manager_skips_sweep_when_fronting_disabled():
    block=GAS[GAS.index('def sweep_once():'):GAS.index('def gas_sweep_loop():')]
    assert "if not getattr(_app, 'ORCAGENT_FRONTS_GAS', True):" in block
    assert 'return' in block
    assert block.index("ORCAGENT_FRONTS_GAS") < block.index('_users_with_evm_key()')


def test_singleflight_shape_is_present():
    block=SRC[SRC.index('def _evm_read_with_fallback'):SRC.index('# Minimal ERC20/BEP20 ABI')]
    assert '_evm_read_locks.get(cache_key)' in block
    assert 'with lock:' in block
    assert block.count('_evm_read_cache.get(cache_key)') >= 2


if __name__=='__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL EVM RPC RESILIENCE REGRESSIONS PASSED')
