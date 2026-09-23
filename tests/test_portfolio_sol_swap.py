import contextlib
import importlib.util
import sqlite3
import sys
import tempfile
import types
import unittest
from decimal import Decimal
from unittest.mock import Mock, patch
from flask import Flask

provider = types.ModuleType('solana_source_bridge_gasless')
with patch.dict(sys.modules, {'solana_source_bridge_gasless': provider}):
    import portfolio_sol_swap as swap

class SwapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.wallet = 'alice'
        self.sol = '0'
        self.usdc = '20.088712'
        self.db = self.tmp.name + '/test.db'
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE users(wallet_address TEXT, encrypted_private_key TEXT)')
            c.execute("INSERT INTO users VALUES ('alice','encrypted')")
        self.order = dict(inAmount='20088712', outAmount='120000000', otherAmountThreshold='119000000',
                          requestId='request', transaction='unsigned', gasless=True)
        provider._gasless_order = Mock(side_effect=lambda key, amount:(dict(self.order, inAmount=str(int(amount*1000000))),Decimal('0.12')))
        provider._execute_order = Mock(return_value=('tx', {}))
        d = types.SimpleNamespace(app=self.app, DB_FILE=self.db, SOL_NETWORK_RESERVE=0.005,
            JUPITER_PROXY='', PROXY_SECRET='', USDC_MINT='usdc', SOL_MINT='sol',
            _authenticated_wallet=lambda:self.wallet, _validate_csrf=lambda v:v=='valid',
            _get_trading_wallet_address=lambda w:'trading', _get_user_sol=lambda a:self.sol,
            _get_solana_usdc_balance=lambda a:self.usdc, _use_key=lambda b,w:contextlib.nullcontext('test-key'),
            _redact_keys=str, rate_limit=lambda *a:lambda f:f)
        swap.install(d)
        self.client=self.app.test_client()
    def tearDown(self):
        self.tmp.cleanup()
    def quote(self, amount='20.088712'):
        return self.client.get('/api/wallet/sol-swap/quote?amount='+amount)
    def execute(self, token, csrf='valid'):
        return self.client.post('/api/wallet/sol-swap/execute',json={'quote_id':token},headers={'X-CSRF-Token':csrf})
    def test_zero_sol_max_and_execution(self):
        b=self.client.get('/api/wallet/sol-swap/balance').json
        self.assertEqual(b['max_usdc'],'20.088712')
        self.assertEqual(Decimal(b['max_sol']),0)
        q=self.quote()
        self.assertEqual(q.status_code,200)
        self.assertTrue(q.json['gasless'])
        self.assertEqual(self.execute(q.json['quote_id']).status_code,200)
        self.assertEqual(self.execute(q.json['quote_id']).status_code,409)
        provider._execute_order.assert_called_once()
    def test_native_max_reserves_gas(self):
        self.sol='0.123456789'
        b=self.client.get('/api/wallet/sol-swap/balance').json
        self.assertEqual(b['max_sol'],'0.118456789')
    def test_funded_wallet_uses_normal_swap_instead_of_requiring_gasless(self):
        self.sol='0.005'
        response=types.SimpleNamespace(status_code=200, json=lambda:{
            'outAmount':'120000000', 'otherAmountThreshold':'119000000',
            'priceImpactPct':'0.0001'})
        with patch.object(swap.requests,'get',return_value=response) as request_quote:
            q=self.quote('1')
        self.assertEqual(q.status_code,200)
        self.assertFalse(q.json['gasless'])
        self.assertNotIn('quote_id',q.json)
        self.assertEqual(q.json['network_reserve_native'],0.005)
        provider._gasless_order.assert_not_called()
        self.assertEqual(request_quote.call_args.kwargs['params']['inputMint'],'usdc')
        self.assertEqual(request_quote.call_args.kwargs['params']['outputMint'],'sol')
    def test_auth_csrf_and_ownership(self):
        token=self.quote().json['quote_id']
        self.assertEqual(self.execute(token,'wrong').status_code,403)
        self.wallet='bob'
        self.assertEqual(self.execute(token).status_code,409)
        self.wallet=None
        self.assertEqual(self.quote().status_code,401)
        provider._execute_order.assert_not_called()
    def test_expired_quote(self):
        token=self.quote().json['quote_id']
        with sqlite3.connect(self.db) as c:c.execute('UPDATE portfolio_sol_swap_orders SET expires=0')
        self.assertEqual(self.execute(token).status_code,409)
        provider._execute_order.assert_not_called()
    def test_invalid_and_excess_amounts(self):
        for value in ['nan','inf','-1','0','0.0000001','21']:
            self.assertNotEqual(self.quote(value).status_code,200)
        provider._execute_order.assert_not_called()
    def test_provider_rejection_and_balance_change(self):
        provider._gasless_order.side_effect=RuntimeError('No gasless route')
        self.assertNotEqual(self.quote().status_code,200)
        provider._execute_order.assert_not_called()
    def test_uncertain_execution_consumes_quote(self):
        token=self.quote().json['quote_id']
        provider._execute_order.side_effect=RuntimeError('timeout')
        self.assertEqual(self.execute(token).status_code,502)
        self.assertEqual(self.execute(token).status_code,409)
        provider._execute_order.assert_called_once()
    def test_balance_decreased_after_review(self):
        token=self.quote().json['quote_id']
        self.usdc='1'
        self.assertEqual(self.execute(token).status_code,400)
        provider._execute_order.assert_not_called()
if __name__=='__main__': unittest.main()
