"""The auto-trading bot trades Solana USDC, so it must start on a USDC balance.

It used to demand at least 0.05 SOL before starting, even though every buy is
paid in USDC and Jupiter Ultra gasless takes the network fee from that USDC.
"""
import ast
import contextlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'dashboard.py').read_text()


def load(name, ns):
    tree = ast.parse(SRC)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'dashboard.py', 'exec'), ns)
    return ns[name]


class BotStartGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = self.tmp.name + '/t.db'
        with sqlite3.connect(self.db) as c:
            c.execute('CREATE TABLE users(wallet_address TEXT, min_trade_size REAL)')
            c.execute("INSERT INTO users VALUES ('w', 1.0)")
        self.usdc = Mock(return_value=19.57)
        self.sol = Mock(return_value=0.0048)
        self.legacy = Mock(return_value=('legacy', 'tw', 0.0, 0.05))
        self.gasless = True
        keypair = type('KP', (), {'from_base58_string': staticmethod(
            lambda k: type('K', (), {'pubkey': lambda s: 'trading-wallet'})())})
        import sys, types
        sys.modules['solders.keypair'] = types.SimpleNamespace(Keypair=keypair)
        self.ns = dict(sqlite3=sqlite3, DB_FILE=self.db, SOLANA_BASE_CURRENCY='USDC',
                       _use_key=lambda *a: contextlib.nullcontext('key'),
                       _get_solana_usdc_balance=self.usdc, _get_user_sol=self.sol,
                       _solana_usdc_buy_gasless_enabled=lambda: self.gasless,
                       _insufficient_trade_balance=self.legacy)
        self.gate = load('_insufficient_bot_balance', self.ns)

    def tearDown(self):
        self.tmp.cleanup()

    def test_usdc_funded_wallet_starts_without_sol(self):
        msg, wallet, cur, req, ccy = self.gate('w', 'blob')
        self.assertIsNone(msg)
        self.assertEqual((wallet, ccy), ('trading-wallet', 'USDC'))
        self.sol.assert_not_called()
        self.legacy.assert_not_called()

    def test_short_on_usdc_reports_usdc(self):
        self.usdc.return_value = 0.5
        msg, wallet, cur, req, ccy = self.gate('w', 'blob')
        self.assertIn('Insufficient USDC', msg)
        self.assertEqual((cur, req, ccy), (0.5, 1.0, 'USDC'))

    def test_sol_gas_still_required_without_gasless(self):
        self.gasless = False
        msg, _, cur, req, ccy = self.gate('w', 'blob')
        self.assertIn('network fees', msg)
        self.assertEqual((cur, req, ccy), (0.0048, 0.005, 'SOL'))

    def test_unreadable_usdc_balance_does_not_block(self):
        self.usdc.side_effect = RuntimeError('rpc down')
        self.assertIsNone(self.gate('w', 'blob')[0])

    def test_sol_base_keeps_legacy_gate(self):
        self.ns['SOLANA_BASE_CURRENCY'] = 'SOL'
        self.assertEqual(self.gate('w', 'blob'), ('legacy', 'tw', 0.0, 0.05, 'SOL'))


class WiringTests(unittest.TestCase):
    def test_both_bot_start_routes_use_the_usdc_gate(self):
        for route in ('def bot_start():', 'def start_trader():'):
            body = SRC.split(route, 1)[1].split('\n@app.route', 1)[0]
            self.assertIn('_insufficient_bot_balance(wallet, kr[0])', body)
            self.assertNotIn('_insufficient_trade_balance(', body)

    def test_copy_trade_keeps_its_sol_gate(self):
        self.assertIn('_insufficient_trade_balance(wallet, key_row[0])', SRC)

    def test_gasless_usdc_buys_pass_the_loop_gas_gate(self):
        self.assertIn('and (us_sol >= _GAS_MIN or _gasless_usdc_buy)', SRC)


if __name__ == '__main__':
    unittest.main()
