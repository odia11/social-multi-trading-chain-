import sqlite3
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from flask import Flask
from live_trades_truth import install, normalize

class TruthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = self.tmp.name + '/test.db'
        with sqlite3.connect(db) as c:
            c.executescript("""
                CREATE TABLE users(id INTEGER,wallet_address TEXT,encrypted_private_key TEXT);
                INSERT INTO users VALUES(1,'alice','encrypted'),(2,'bob','encrypted');
                CREATE TABLE open_positions(user_id INTEGER,mint_address TEXT,source TEXT,chain TEXT,base_currency TEXT);
                INSERT INTO open_positions VALUES(1,'mint-a','bot','solana','SOL'),(2,'mint-b','bot','solana','SOL');
            """)
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.wallet = 'alice'
        self.lock = threading.Lock()
        pos = dict(amount=100, buy_price=.001, spend=.1, base='SOL', symbol='CAT', source='bot')
        self.us = {'positions': {'mint-a': pos}}
        raw = dict(token='CAT',mint_address='mint-a',amount=100,entry_price=.001,
                   current_price=.16,tp_price=.0012,sl_price=.0009,price_known=True)
        self.d = SimpleNamespace(app=self.app, DB_FILE=db, _sol_price_usd=150,
            _authenticated_wallet=lambda:self.wallet, rate_limit=lambda *a:lambda f:f,
            is_valid_solana_address=lambda m:m.startswith('mint-'),
            _sec_check_state={}, _get_sell_lock=lambda *a:self.lock,
            _get_trading_wallet_address=lambda w:'trading-'+w,
            _known_wallet_token_accounts=Mock(return_value=[{'mint':'mint-a','amount':80}]),
            _fetch_open_bot_positions=lambda w:[raw] if w=='alice' else [],
            _fetch_closed_bot_trades=lambda w:[], _bot_status_summary=lambda w:{},
            get_user_state=lambda w:self.us, get_token_data=lambda *a,**k:{'price':.16},
            _bot_execute_exit_locked=Mock(return_value=(True,.001,80)),
            _close_open_position=Mock(), _wallet_tokens_cache={},
            _get_csrf_token=lambda:'test', redirect=lambda path:'redirect',
            _render_no_cache=lambda *a,**k:k)
        install(self.d)
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmp.cleanup()

    def sell(self, mint='mint-a'):
        return self.client.post('/api/live-trades/sell',json={'mint_address':mint})

    def test_units_and_actual_amount(self):
        p = self.d._fetch_open_bot_positions('alice')[0]
        self.assertAlmostEqual(p['entry_price'],.15)
        self.assertAlmostEqual(p['pnl_pct'],6.67)
        self.assertAlmostEqual(p['pnl_usd'],.8)
        self.assertEqual(p['amount'],80)

    def test_phantom_rows_hidden(self):
        self.d._known_wallet_token_accounts.return_value = []
        self.assertEqual(self.d._fetch_open_bot_positions('alice'),[])

    def test_outage_not_zero_or_profit(self):
        self.d._known_wallet_token_accounts.side_effect = RuntimeError('rpc')
        p = self.d._fetch_open_bot_positions('alice')[0]
        self.assertFalse(p['can_sell'])
        self.assertIsNone(p['pnl_usd'])
        self.assertIsNone(p['pnl_pct'])

    def test_no_sol_rate_no_invented_pnl(self):
        p = normalize({'amount':5,'entry_price':.1,'current_price':20,'price_known':True},'SOL',0,5)
        self.assertIsNone(p['pnl_usd'])

    def test_usdc_not_converted(self):
        p = normalize({'amount':5,'entry_price':2,'current_price':3,'price_known':True},'USDC',150,5)
        self.assertEqual(p['pnl_usd'],5)

    def test_success_uses_shared_lock_and_preserves_source(self):
        def execute(*args):
            self.assertTrue(self.lock.locked())
            self.assertEqual(args[5],.16/150)
            self.assertEqual(args[7],80)
            self.assertEqual(args[9],'MANUAL OVERRIDE')
            self.assertEqual(args[4]['source'],'bot')
            return True,.001,80
        self.d._bot_execute_exit_locked.side_effect = execute
        def close(*args):
            self.assertTrue(self.lock.locked())
        self.d._close_open_position.side_effect = close
        self.assertEqual(self.sell().status_code,200)
        self.assertFalse(self.lock.locked())
        self.d._known_wallet_token_accounts.assert_called_with('alice','trading-alice')

    def test_failed_sell_retains_position(self):
        self.d._bot_execute_exit_locked.return_value = (False,0,0)
        self.assertEqual(self.sell().status_code,502)
        self.d._close_open_position.assert_not_called()

    def test_zero_balance_no_sell(self):
        self.d._known_wallet_token_accounts.return_value=[]
        self.assertEqual(self.sell().status_code,409)
        self.d._bot_execute_exit_locked.assert_not_called()

    def test_other_account_no_sell(self):
        self.assertEqual(self.sell('mint-b').status_code,404)
        self.d._bot_execute_exit_locked.assert_not_called()

    def test_concurrent_bot_exit_no_double_sell(self):
        self.lock.acquire()
        try:
            self.assertEqual(self.sell().status_code,409)
            self.d._bot_execute_exit_locked.assert_not_called()
        finally:
            self.lock.release()

    def test_paused_and_unauthenticated(self):
        self.wallet=''
        self.assertEqual(self.sell().status_code,401)
        self.wallet='alice'
        self.d._sec_check_state['trading_paused']=True
        self.assertEqual(self.sell().status_code,503)

    def test_fresh_verification_for_sell(self):
        self.d._fetch_open_bot_positions('alice')
        self.d._known_wallet_token_accounts.return_value=[]
        self.assertEqual(self.sell().status_code,409)

if __name__ == '__main__':
    unittest.main()
