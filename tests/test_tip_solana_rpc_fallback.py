"""Static regression guards for Solana tip RPC failover."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'portfolio_token_withdraw.py').read_text()


def block(a,b):
    x=SRC.index(a); y=SRC.index(b,x); return SRC[x:y]


def test_tip_builds_same_rpc_pool_as_dashboard():
    b=block('def _rpc_urls', '\ndef _rpc_call(')
    assert 'CLAIM_SOL_RPCS' in b
    assert '_PROXY_RPCS' in b
    assert 'SOLANA_RPC' in b


def test_rpc_any_skips_broken_or_empty_token_account_provider():
    b=block('def _rpc_call_any', '\ndef _solana_transfer')
    assert 'for url in _rpc_urls(d):' in b
    assert 'require_nonempty' in b
    assert 'continue' in b
    assert 'return result, url' in b


def test_tip_readiness_does_not_use_single_rpc():
    b=block('def _tip_solana_ready', '\ndef _tip_evm_candidates')
    assert '_rpc_call_any' in b
    assert '_rpc_call(url' not in b
    assert 'getBalance' in b


def test_solana_tip_transfer_fails_over_for_token_account_and_reads():
    b=block('def _solana_transfer', '\ndef _evm_transfer')
    assert "_rpc_call_any(d, 'getTokenAccountsByOwner'" in b
    assert "require_nonempty=True" in b
    assert "_rpc_call_any(d, 'getAccountInfo'" in b
    assert "_rpc_call_any(d, 'getBalance'" in b
    assert "_rpc_call_any(d, 'getLatestBlockhash'" in b
    assert "_rpc_call_any(d, 'sendTransaction'" in b


if __name__=='__main__':
    for n in sorted(x for x in globals() if x.startswith('test_')):
        globals()[n]()
        print('PASS',n)
    print('ALL TIP SOLANA RPC FALLBACK REGRESSIONS PASSED')
