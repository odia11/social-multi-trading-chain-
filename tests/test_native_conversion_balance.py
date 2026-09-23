"""Run the conversion handler in isolation; never import production startup."""
import ast
import contextlib
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import Mock

class NativeConversionBalanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = str(Path(self.tmp.name) / 'test.db')
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE users(wallet_address TEXT, encrypted_private_key TEXT)')
            c.execute("INSERT INTO users VALUES ('login-wallet','encrypted')")
        path = Path(os.environ.get('ORCA_ROUTE_SOURCE', Path(__file__).resolve().parents[1] / 'dashboard.py'))
        tree = ast.parse(path.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'api_wallet_convert')
        fn.decorator_list = []
        self.balance = Mock(return_value=0.175574280)
        self.execute = Mock(return_value=(True, 'signature', '', 20, 0.170574280))
        self.data = {'chain':'solana', 'direction':'native_to_stable', 'amount':0.170574280}
        self.ns = dict(
            request=types.SimpleNamespace(get_json=lambda **kw:self.data),
            jsonify=lambda obj:obj, _authenticated_wallet=lambda:'login-wallet',
            sqlite3=sqlite3, DB_FILE=db, math=math, EVM_CHAINS={},
            _get_trading_wallet_address=lambda wallet:'trading-wallet',
            _get_user_sol=self.balance, SOL_NETWORK_RESERVE=0.005,
            _use_key=lambda *a:contextlib.nullcontext('test-key'),
            _execute_user_swap_ex=self.execute, USDC_MINT='usdc',
            _log_security_event=lambda *a:None, add_user_log=lambda *a:None,
            fetch_user_balances=Mock(side_effect=AssertionError('must not read login wallet')),
            get_user_state=Mock(side_effect=AssertionError('must not read rounded cached balance'))
        )
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), self.ns)
    def tearDown(self):
        self.tmp.cleanup()
    def test_exact_max_uses_funded_trading_wallet(self):
        response=self.ns['api_wallet_convert']()
        self.assertTrue(response['ok'])
        self.balance.assert_called_once_with('trading-wallet')
        self.execute.assert_called_once()
    def test_spending_reserve_is_rejected(self):
        self.data['amount']=0.175574280
        response,status=self.ns['api_wallet_convert']()
        self.assertEqual(status,400)
        self.execute.assert_not_called()
    def test_rpc_failure_is_not_reported_as_zero(self):
        self.balance.side_effect=RuntimeError('RPC unavailable')
        response,status=self.ns['api_wallet_convert']()
        self.assertEqual(status,502)
        self.assertIn('balance unavailable',response['msg'])
        self.execute.assert_not_called()
    def test_missing_trading_wallet_does_not_fall_back_to_login(self):
        self.ns['_get_trading_wallet_address']=lambda w:None
        response,status=self.ns['api_wallet_convert']()
        self.assertEqual(status,400)
        self.balance.assert_not_called()
        self.execute.assert_not_called()

if __name__=='__main__': unittest.main()
