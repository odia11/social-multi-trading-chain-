"""No signing or RPC: simulate provider responses to rejected Solana tips."""
import types
from unittest.mock import patch

import portfolio_token_withdraw as m


def response(error):
    return types.SimpleNamespace(status_code=200, json=lambda: {'jsonrpc':'2.0','id':1,'error':error})


def test_simulation_exposes_program_reason_without_raw_payload():
    error = {'code': -32002, 'message': 'Transaction simulation failed',
             'data': {'err': {'InstructionError': [0, {'Custom': 1}]},
                      'logs': ['Program log: Instruction: TransferChecked',
                               'Program log: Error: insufficient funds',
                               'Program Tokenkeg failed: custom program error: 0x1']}}
    with patch.object(m.requests, 'post', return_value=response(error)):
        try:
            m._rpc_call('https://example.invalid', 'sendTransaction', ['signed-transaction-placeholder'])
            raise AssertionError('simulation failure was not raised')
        except m._SolanaPreflightError as exc:
            assert 'custom program error: 0x1' in str(exc)
            assert not exc.gas_shortfall  # token balance failure is NOT SOL shortage
            assert exc.reason_code == 'program_rejected'


def test_real_sol_shortfall_is_specific():
    error = {'code': -32002, 'message': 'Transaction simulation failed',
             'data': {'err': {'InsufficientFundsForFee': None},
                      'logs': ['Program log: insufficient lamports for rent']}}
    exc=m._preflight_error_from_rpc(error)
    assert exc.gas_shortfall and exc.reason_code == 'insufficient_sol'


def test_stale_blockhash_is_not_relabelled_as_gas():
    exc=m._preflight_error_from_rpc({
        'message': 'Transaction simulation failed',
        'data': {'err':'BlockhashNotFound', 'logs': []}})
    assert not exc.gas_shortfall
    assert exc.reason_code == 'expired_blockhash'


def test_provider_failure_does_not_erase_preflight_error():
    error={'code': -32002, 'message':'Transaction simulation failed',
           'data':{'err': {'InstructionError':[1,{'Custom':1}]},
                   'logs':['Program log: Error: insufficient funds']}}
    calls=[]
    def post(url, **kwargs):
        calls.append(url)
        return response(error)
    with patch.object(m, '_rpc_urls', return_value=['https://one.invalid','https://two.invalid']):
        with patch.object(m.requests, 'post', side_effect=post):
            try:
                m._rpc_call_any(object(), 'sendTransaction', ['placeholder'])
                raise AssertionError('simulation failure was not raised')
            except m._SolanaPreflightError as exc:
                assert 'insufficient funds' in str(exc)
    assert calls == ['https://one.invalid']



def test_blockhash_and_send_prefer_same_rpc():
    from pathlib import Path
    src=(Path(__file__).resolve().parents[1]/'portfolio_token_withdraw.py').read_text()
    a=src.index('def _solana_transfer')
    b=src.index('def _evm_transfer', a)
    block=src[a:b]
    assert "bh_result, blockhash_rpc = _rpc_call_any(d, 'getLatestBlockhash'" in block
    assert 'preferred_url=blockhash_rpc' in block
    calls=[]
    def fake_call(url, method, params):
        calls.append(url)
        return 'signature'
    dummy=types.SimpleNamespace()
    with patch.object(m, '_rpc_urls', return_value=['https://a.invalid','https://b.invalid']):
        with patch.object(m, '_rpc_call', side_effect=fake_call):
            _, chosen=m._rpc_call_any(dummy, 'sendTransaction', ['signed'], preferred_url='https://b.invalid')
    assert chosen == 'https://b.invalid'
    assert calls == ['https://b.invalid']


def test_no_simulation_error_dump_for_ordinary_reads():
    error={'code':429,'message':'rate limited'}
    with patch.object(m.requests,'post',return_value=response(error)):
        try:
            m._rpc_call('https://example.invalid', 'getBalance', ['wallet'])
            raise AssertionError('rate limit was not raised')
        except RuntimeError as exc:
            assert not isinstance(exc,m._SolanaPreflightError)
            assert str(exc)=='rate limited'


if __name__=='__main__':
    for name in sorted(k for k in globals() if k.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL TIP SIMULATION DIAGNOSTICS REGRESSIONS PASSED')
