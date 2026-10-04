"""Native money movement: real signatures, mocked RPC, no network or funds."""
import ast
import base64
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import Message
from solders.transaction import Transaction

import sol_native_payments as pay
import portfolio_token_withdraw as provider


@pytest.mark.parametrize('value', ['nan', 'inf', '-1', '0', '0.0000000001', None, 'bad'])
def test_invalid_native_amounts(value):
    with pytest.raises(ValueError):
        pay.lamports(value)


def test_exact_native_precision():
    assert pay.lamports('0.000000001') == 1
    assert pay.lamports('1.123456789') == 1123456789


def fixture(tmp_path, send_error=None, balance=1_000_000_000):
    key, recipient = Keypair(), str(Keypair().pubkey())
    calls, transactions = [], []
    @contextmanager
    def use_key(*args):
        yield str(key)
    d = SimpleNamespace(DB_FILE=str(tmp_path/'db.sqlite'), _use_key=use_key,
                        is_valid_solana_address=lambda _: True)
    def rpc(d, method, params, **kw):
        calls.append(method)
        result = {'getBalance': {'value': balance},
                  'getLatestBlockhash': {'value': {'blockhash': str(Hash.default())}},
                  'getFeeForMessage': {'value': 5000}}.get(method)
        if method == 'sendTransaction':
            assert params[1]['preflightCommitment'] == 'confirmed'
            assert params[1]['skipPreflight'] is False
            tx = Transaction.from_bytes(base64.b64decode(params[0]))
            tx.verify()
            transactions.append(tx)
            assert params[1]['skipPreflight'] is False
            if send_error:
                raise send_error
            result = str(tx.signatures[0])
        return result, 'mock-rpc'
    return d, recipient, calls, transactions, rpc


def test_native_transfer_budget_and_durable_duplicate(tmp_path):
    d, recipient, calls, transactions, rpc = fixture(tmp_path)
    with patch.object(provider, '_wallet_keys', return_value=('encrypted',)), \
         patch.object(provider, '_fee_payer_rent_lamports', return_value=890880), \
         patch.object(provider, '_rpc_call_any', side_effect=rpc):
        result = pay.native_transfer(d, 'user', recipient, '0.01', 'same-request-123456')
        assert result[1] == 0.009995
        assert pay.native_transfer(d, 'user', recipient, '0.01', 'same-request-123456') == result
        assert calls.count('sendTransaction') == 1
        # The signed SystemProgram instruction sends only budget minus fee.
        instruction = transactions[0].message.instructions[0]
        assert int.from_bytes(bytes(instruction.data)[4:12], 'little') == 9995000
        with pytest.raises(ValueError, match='different amount'):
            pay.native_transfer(d, 'user', recipient, '0.02', 'same-request-123456')


def test_ambiguous_submission_keeps_same_signature(tmp_path):
    d, recipient, calls, transactions, rpc = fixture(tmp_path, TimeoutError())
    with patch.object(provider, '_wallet_keys', return_value=('encrypted',)), \
         patch.object(provider, '_fee_payer_rent_lamports', return_value=890880), \
         patch.object(provider, '_rpc_call_any', side_effect=rpc):
        result = pay.native_transfer(d, 'user', recipient, '0.01', 'timeout-request-1234')
        assert result[0] == str(transactions[0].signatures[0])
        assert pay.native_transfer(d, 'user', recipient, '0.01', 'timeout-request-1234') == result
        assert calls.count('sendTransaction') == 1


def test_reserve_cannot_be_sent(tmp_path):
    d, recipient, calls, transactions, rpc = fixture(tmp_path, balance=10_000_000)
    with patch.object(provider, '_wallet_keys', return_value=('encrypted',)), \
         patch.object(provider, '_fee_payer_rent_lamports', return_value=890880), \
         patch.object(provider, '_rpc_call_any', side_effect=rpc):
        with pytest.raises(ValueError, match='reserve'):
            pay.native_transfer(d, 'user', recipient, '0.01', 'reserve-request-1234')
    assert 'sendTransaction' not in calls


def test_preflight_failure_cannot_be_reported_as_submitted_or_replayed(tmp_path):
    d, recipient, calls, transactions, rpc = fixture(tmp_path, provider._SolanaPreflightError('InsufficientFundsForRent'))
    with patch.object(provider, '_wallet_keys', return_value=('encrypted',)), \
         patch.object(provider, '_fee_payer_rent_lamports', return_value=890880), \
         patch.object(provider, '_rpc_call_any', side_effect=rpc):
        with pytest.raises(provider._SolanaPreflightError):
            pay.native_transfer(d, 'user', recipient, '0.01', 'rejected-request-123')
        with pytest.raises(ValueError, match='failed'):
            pay.native_transfer(d, 'user', recipient, '0.01', 'rejected-request-123')
        assert calls.count('sendTransaction') == 1


def test_native_http_contract(tmp_path):
    from flask import Flask
    app = Flask(__name__)
    app.add_url_rule('/api/withdraw', 'api_withdraw', lambda: '', methods=['POST'])
    app.add_url_rule('/api/wallet/send', 'wallet_send', lambda: '', methods=['POST'])
    wallet = ['user']
    d = SimpleNamespace(app=app, _authenticated_wallet=lambda: wallet[0],
        rate_limit=lambda *a: lambda f: f, _get_trading_wallet_address=lambda w: 'trading',
        SOL_NETWORK_RESERVE=0.005, SOLANA_MIN_SPEND_SOL=0.006, _sol_price_usd=100)
    pay.install(d)
    client = app.test_client()
    with patch.object(provider, '_csrf_ok', return_value=True), \
         patch.object(pay, 'native_transfer', return_value=('signature', .009995)) as send, \
         patch.object(provider, '_rpc_call_any', return_value=({'value': 1000000000}, 'mock')):
        assert client.post('/api/withdraw', json={'amount_usdc': .01}).status_code == 400
        assert send.call_count == 0
        for path in ('/api/withdraw', '/api/wallet/send'):
            response = client.post(path, json={'amount_sol': .01, 'to': 'recipient', 'request_id': 'unique-request-123'})
            assert response.status_code == 200
            assert response.json['status'] == 'submitted'
            assert response.json['currency'] == 'SOL'
            assert response.json['amount_sent'] == .009995
        balance = client.get('/api/wallet/trading-balance')
        assert balance.json['available_sol'] == .995
        assert balance.headers['Cache-Control'] == 'private, no-store'
        wallet[0] = None
        assert client.post('/api/withdraw', json={'amount_sol': .01}).status_code == 401
    wallet[0] = 'user'
    with patch.object(provider, '_csrf_ok', return_value=False), patch.object(pay, 'native_transfer') as send:
        assert client.post('/api/withdraw', json={'amount_sol': .01}).status_code == 403
        send.assert_not_called()


def test_mixed_currency_daily_risk_limits(tmp_path):
    import sqlite3
    node = next(n for n in ast.parse(Path('dashboard.py').read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_daily_realized_pnl_usd')
    path = str(tmp_path/'risk.sqlite')
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE users(id INTEGER,wallet_address TEXT);
            CREATE TABLE trades(user_id INTEGER,chain TEXT,base_currency TEXT,pnl REAL,timestamp TEXT);
            INSERT INTO users VALUES(1,'user');
            INSERT INTO trades VALUES(1,'solana','USDC',-5,date('now'));
            INSERT INTO trades VALUES(1,'solana','SOL',-.2,date('now'));
            INSERT INTO trades VALUES(1,'solana','USDC',-100,'2000-01-01');""")
    namespace = {'sqlite3': sqlite3, 'DB_FILE': path, '_sol_price_usd': 100}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<daily-risk>', 'exec'), namespace)
    assert namespace['_daily_realized_pnl_usd']('user') == -25
    namespace['_sol_price_usd'] = 0
    assert namespace['_daily_realized_pnl_usd']('user') == float('-inf')


def test_native_trade_history_keeps_confirmed_amounts_and_signatures(tmp_path):
    import sqlite3
    from flask import Flask, jsonify, request
    import portfolio_trade_history as history
    path=str(tmp_path/'history.sqlite')
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TABLE trades(id INTEGER,user_id INTEGER,token TEXT,
            amount REAL,timestamp TEXT,mint_address TEXT,side TEXT,base_currency TEXT,
            tx_hash TEXT,source TEXT,chain TEXT,entry_price REAL,exit_price REAL,pnl REAL);
            INSERT INTO trades VALUES(1,1,'TOKEN',.01,'2026-10-04T10:00:00','mint','buy','SOL',
                'buy-signature','manual','solana',0,0,0);
            INSERT INTO trades VALUES(2,1,'TOKEN',.015,'2026-10-04T11:00:00','mint','sell','SOL',
                'sell-signature','manual','solana',0,0,0);""")
    app=Flask(__name__)
    d=SimpleNamespace(app=app,DB_FILE=path,_authenticated_wallet=lambda:'user',
        _get_uid=lambda conn,wallet:1,jsonify=jsonify,request=request,_sol_price_usd=100)
    history.install(d)
    rows=app.test_client().get('/api/portfolio/transactions').json['transactions']
    assert len(rows)==2
    assert [(r['side'],r['amount_base'],r['currency'],r['tx_hash']) for r in rows]==[
        ('sell',.015,'SOL','sell-signature'),('buy',.01,'SOL','buy-signature')]
    assert rows[0]['amount_usd']==1.5
    assert len(app.test_client().get('/api/portfolio/transactions?side=buy').json['transactions'])==1


def budget_function():
    # Extract only the guard so the test cannot initialize a live trading bot.
    source = Path('orcagent_solana.py').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_assert_native_budget')
    namespace = {'base64': base64, '_BUY_MAX_OUTFLOW_LAMPORTS': 10_000_000}
    error = next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='NativeBuyBudgetExceeded')
    exec(compile(ast.Module(body=[error,node], type_ignores=[]), '<budget>', 'exec'), namespace)
    return namespace


@pytest.mark.parametrize('final,fee,error,allowed', [
    (990_010_000, 5000, None, True),
    (989_000_000, 5000, None, False),
    (990_010_000, None, None, False),
    (990_010_000, 5000, 'AccountNotFound', False),
    (None, 5000, None, False),
])
def test_swap_budget_guard(final, fee, error, allowed):
    namespace = budget_function()
    def rpc(body, **kw):
        return {'result': {'value': {
            'getBalance': 1_000_000_000,
            'getFeeForMessage': fee,
            'simulateTransaction': {'err': error, 'accounts': [{'lamports': final}]}
        }[body['method']]}}
    namespace['_rpc_post'] = rpc
    key = Keypair()
    message = Message.new_with_blockhash([], key.pubkey(), Hash.default())
    tx = Transaction([key], message, Hash.default())
    if allowed:
        namespace['_assert_native_budget']('mock', tx)
    else:
        with pytest.raises(RuntimeError):
            namespace['_assert_native_budget']('mock', tx)


def test_historical_usdc_sell_receives_sol_and_keeps_usd_cost_units():
    node = next(n for n in ast.parse(Path('dashboard.py').read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == '_sell_and_get_realized')
    calls = []
    def swap(*args, **kw):
        calls.append(kw['base'])
        return True, 'sig', '', 10, 0.2
    namespace = {'_sol_price_usd': 100, '_execute_user_swap_ex': swap}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<sell>', 'exec'), namespace)
    sell = namespace['_sell_and_get_realized']
    assert sell('wallet', 'key', 'mint', '100%', 0, 10, base='USDC') == (True, 2.0, 10)
    assert sell('wallet', 'key', 'mint', '100%', 0, 10, base='SOL') == (True, 0.02, 10)
    assert calls == ['SOL', 'SOL']


@pytest.mark.parametrize('existing,expected', [(True,220000),(False,2259280)])
def test_small_sol_usdc_conversion_accounts_for_actual_rent(existing,expected):
    import orcagent_solana as engine
    calls=[]
    def rpc(payload, **kw):
        calls.append(payload['method'])
        return {'result': {'value': {'owner':engine.TOKEN_PROGRAM} if existing else None}} if payload['method']=='getAccountInfo' else {'result':2039280}
    with patch.object(engine,'WALLET_ADDRESS',str(Keypair().pubkey())),patch.object(engine,'_rpc_post',side_effect=rpc):
        allowance=engine._native_buy_cost_allowance(engine.USDC_MINT)
        assert allowance==expected
        assert 2909000-allowance>0  # screenshot's small wallet can quote a remainder
        assert engine._native_buy_cost_allowance('other-token')==3000000
    assert calls==(['getAccountInfo'] if existing else ['getAccountInfo','getMinimumBalanceForRentExemption'])


def test_conversion_unknown_rent_fails_before_swap():
    import orcagent_solana as engine
    with patch.object(engine,'WALLET_ADDRESS',str(Keypair().pubkey())),patch.object(engine,'_rpc_post',return_value={'error':{'code':429}}):
        with pytest.raises(RuntimeError,match='not sent'):
            engine._native_buy_cost_allowance(engine.USDC_MINT)


@pytest.mark.parametrize('rejected',[False,True])
def test_tip_http_signed_payment_or_explicit_rejection(tmp_path,rejected):
    import sqlite3
    from flask import Flask
    d,recipient,calls,transactions,rpc=fixture(tmp_path,provider._SolanaPreflightError('Recent Solana blockhash expired before submission',reason_code='expired_blockhash') if rejected else None)
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute('CREATE TABLE users(id INTEGER,username TEXT,wallet_address TEXT,encrypted_private_key TEXT)')
        db.executemany('INSERT INTO users VALUES(?,?,?,?)',[(1,'sender','sender','encrypted'),(2,'recipient',recipient,None)])
    d.app=Flask(__name__)
    d._authenticated_wallet=lambda:'sender'
    d._validate_csrf=lambda token:token=='valid'
    d._get_trading_wallet_address=lambda wallet:wallet
    provider._RECENT.clear()
    provider.install(d)
    with patch.object(provider,'_wallet_keys',return_value=('encrypted',)),patch.object(provider,'_fee_payer_rent_lamports',return_value=890880),patch.object(provider,'_rpc_call_any',side_effect=rpc):
        response=d.app.test_client().post('/api/tip',headers={'X-CSRF-Token':'valid'},json={'recipient_user_id':2,'amount':0.002,'currency':'SOL','request_id':'tip-http-request-12345'})
    assert calls.count('sendTransaction')==1
    if rejected:
        assert response.status_code==400
        assert response.json['status']=='failed'
        assert response.json['reason_code']=='expired_blockhash'
        assert 'blockhash' in response.json['error']
    else:
        assert response.status_code==200
        assert response.json['status']=='submitted'
        assert response.json['amount_sent']==0.001995
        assert response.json['tx_hash']==str(transactions[0].signatures[0])
        with sqlite3.connect(d.DB_FILE) as db:
            row=db.execute('SELECT amount,currency,status FROM tip_transactions').fetchone()
        assert row==(0.001995,'SOL','submitted')


def test_conversion_quote_uses_same_cost_allowance_as_execution():
    import math, requests
    from flask import Flask,jsonify,request
    from unittest.mock import Mock
    source=Path(__file__).resolve().parents[1].joinpath('dashboard.py').read_text()
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='api_wallet_convert_quote')
    node.decorator_list=[]
    ns=dict(_authenticated_wallet=lambda:'sender',_get_trading_wallet_address=lambda _:str(Keypair().pubkey()),
        request=request,jsonify=jsonify,math=math,requests=requests,JUPITER_PROXY='',PROXY_SECRET='',
        SOL_MINT='So11111111111111111111111111111111111111112',USDC_MINT='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',SOL_NETWORK_RESERVE=.005,__name__=__name__,_redact_keys=str)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<conversion-quote>','exec'),ns)
    response=Mock(status_code=200)
    response.json.return_value={'outAmount':'78000','otherAmountThreshold':'76000'}
    app=Flask(__name__)
    with app.test_request_context('/?direction=native_to_stable&amount=0.002909'),patch.object(pay,'sol_usdc_cost_allowance',return_value=2259280),patch.object(requests,'get',return_value=response) as quote:
        result=ns['api_wallet_convert_quote']().json
    assert quote.call_args.kwargs['params']['amount']==649720
    assert result['cost_allowance_sol']==.002259280
    assert result['swap_input_amount']==.000649720
