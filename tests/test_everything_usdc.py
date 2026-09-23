"""Every Solana trade the app starts is funded in USDC.

Copy trading, DM "copy trade", the narrative agent and manual/admin sells used
to fall back to SOL: copy amounts were 0.01-100 SOL, copy buys spent SOL, and
manual sells sold USDC-bought positions into SOL.
"""
import ast
import contextlib
import math
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

SRC = (Path(__file__).resolve().parents[1] / 'dashboard.py').read_text()


def load(name, ns):
    tree = ast.parse(SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    fn.decorator_list = []
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'dashboard.py', 'exec'), ns)
    return ns[name]


def body_of(name):
    tree = ast.parse(SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, fn)


class DB:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = self.tmp.name + '/t.db'
        with sqlite3.connect(self.path) as c:
            c.execute('''CREATE TABLE users(id INTEGER, wallet_address TEXT, encrypted_private_key TEXT,
                         min_trade_size REAL, copy_source TEXT, copy_amount REAL, copy_amount_usdc REAL,
                         max_positions INTEGER, daily_loss_limit REAL, max_trade_size REAL)''')
            c.execute("INSERT INTO users VALUES (1,'me','blob',1.0,NULL,NULL,NULL,5,50,10)")
            c.execute("INSERT INTO users VALUES (2,'usdc-copier','blob',1.0,'leader',NULL,25,5,50,10)")
            c.execute("INSERT INTO users VALUES (3,'legacy-copier','blob',1.0,'leader',0.1,NULL,5,50,10)")

    def get(self, sql, *a):
        with sqlite3.connect(self.path) as c:
            return c.execute(sql, a).fetchone()


class CopyToggleTests(unittest.TestCase):
    def setUp(self):
        self.db = DB()
        self.addCleanup(self.db.tmp.cleanup)
        self.body = {}
        self.gate = Mock(return_value=(None, 'tw', 19.57, 1.0, 'USDC'))
        self.ns = dict(
            _authenticated_wallet=lambda: 'me', request=types.SimpleNamespace(get_json=lambda **k: self.body),
            jsonify=lambda o: o, is_valid_solana_address=lambda a: True, sqlite3=sqlite3,
            DB_FILE=self.db.path, _get_uid=lambda conn, w: 1, SOLANA_BASE_CURRENCY='USDC',
            _sol_price_usd=120.0, math=math, _insufficient_bot_balance=self.gate,
            _insufficient_trade_balance=Mock(side_effect=AssertionError('SOL gate used')),
            _sync_copy_relationship=lambda *a: None, print=lambda *a, **k: None)
        with sqlite3.connect(self.db.path) as c:
            c.execute('CREATE TABLE copy_relationships(copied_wallet TEXT, active INTEGER)')
        self.toggle = load('api_copy_trade_toggle', self.ns)

    def start(self, **amount):
        self.body = dict(target_wallet='leader', **amount)
        return self.toggle()

    def test_usdc_amount_is_stored_in_usdc(self):
        self.assertTrue(self.start(usdc_amount=25)['ok'])
        self.assertEqual(self.db.get('SELECT copy_amount, copy_amount_usdc FROM users WHERE id=1'), (None, 25.0))
        self.gate.assert_called_once()

    def test_old_sol_clients_are_converted_at_the_live_price(self):
        self.start(sol_amount=0.1)
        self.assertEqual(self.db.get('SELECT copy_amount_usdc FROM users WHERE id=1'), (12.0,))

    def test_no_amount_means_own_trade_size(self):
        self.start()
        self.assertEqual(self.db.get('SELECT copy_source, copy_amount_usdc FROM users WHERE id=1'), ('leader', None))

    def test_out_of_range_amount_is_refused(self):
        resp, status = self.start(usdc_amount=0.5)
        self.assertEqual(status, 400)
        self.assertIn('USDC', resp['msg'])

    def test_short_on_usdc_shows_usdc_modal(self):
        self.gate.return_value = ('Insufficient USDC', 'tw', 0.2, 1.0, 'USDC')
        resp, status = self.start(usdc_amount=5)
        self.assertEqual((status, resp['currency'], resp['low_balance']), (400, 'USDC', True))


class CopyBuyTests(unittest.TestCase):
    def setUp(self):
        self.db = DB()
        self.addCleanup(self.db.tmp.cleanup)
        self.buy = Mock(return_value=types.SimpleNamespace(get_json=lambda: {'ok': True}))
        state = {w: {'positions': {}, 'daily_stats': {'total_pnl': 0}} for w in ('usdc-copier', 'legacy-copier')}
        self.ns = dict(
            sqlite3=sqlite3, DB_FILE=self.db.path, _sol_price_usd=120.0, SOLANA_BASE_CURRENCY='USDC',
            USDC_MINT='usdc', MAX_ENTRY_PRICE_IMPACT_PCT=5.0, get_user_state=lambda w: state[w],
            _check_price_impact=Mock(return_value={'ok': True, 'price_impact_pct': 0.1}),
            _solana_buy_flow=self.buy, app=types.SimpleNamespace(app_context=contextlib.nullcontext),
            add_user_log=lambda *a: None, print=lambda *a, **k: None,
            _get_user_sol=Mock(side_effect=AssertionError('copy checked SOL')),
            threading=types.SimpleNamespace(Thread=lambda target, daemon: types.SimpleNamespace(start=target)))
        self.copy = load('_trigger_copy_buy', self.ns)

    def test_copies_buy_with_usdc_through_the_live_market_flow(self):
        self.copy('leader', 'mint', 1.0, 'TKN', 50000)
        calls = {c.args[0]: c.kwargs for c in self.buy.call_args_list}
        self.assertEqual(calls['usdc-copier']['requested_usdc'], 25.0)
        self.assertEqual(calls['legacy-copier']['requested_usdc'], 12.0)  # 0.1 SOL at $120
        for kw in calls.values():
            self.assertEqual((kw['source'], kw['copy_of_wallet'], kw['trigger_copies'], kw['respect_max']),
                             ('copy', 'leader', False, False))
        self.ns['_check_price_impact'].assert_any_call('mint', 25.0, input_mint='usdc', input_decimals=6)


class WiringTests(unittest.TestCase):
    def test_copy_followers_report_usdc_amounts(self):
        db = DB()
        self.addCleanup(db.tmp.cleanup)
        fn = load('_copy_followers', dict(sqlite3=sqlite3, DB_FILE=db.path, _sol_price_usd=120.0,
                                          print=lambda *a, **k: None))
        amounts = {r[1]: r[4] for r in fn('leader')}
        self.assertEqual(amounts, {'usdc-copier': 25.0, 'legacy-copier': 12.0})

    def test_dm_copy_trade_is_a_usdc_buy(self):
        self.assertIn("return _solana_buy_flow(wallet, token_address, log_label='COPY TRADE'",
                      body_of('copy_trade_from_message'))

    def test_manual_sells_go_back_to_the_positions_currency(self):
        for fn in ('api_manual_sell', 'manual_sell'):
            src = body_of(fn)
            self.assertEqual(src.count("base=pos.get('base', 'SOL')"), 2, fn)

    def test_admin_force_close_uses_the_positions_currency(self):
        self.assertIn("base=pos.get('base', 'SOL')", body_of('admin_force_close_all'))

    def test_narrative_agent_buys_and_tags_usdc(self):
        src = body_of('_narrative_agent_process_candidate')
        self.assertIn("str(amount_sol), base=SOLANA_BASE_CURRENCY)", src)
        self.assertIn("pos['base']      = SOLANA_BASE_CURRENCY", src)

    def test_buy_flow_records_copies_as_copies(self):
        src = body_of('_solana_buy_flow')
        self.assertIn('source=source,\n                                  copy_of_wallet=copy_of_wallet)', src)
        self.assertIn('if trigger_copies:', src)


if __name__ == '__main__':
    unittest.main()
