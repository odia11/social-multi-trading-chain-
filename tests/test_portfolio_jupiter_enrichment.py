"""Portfolio token identity, logo, and price fallback from Jupiter."""
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
import portfolio_inventory as inventory

SOL = 'So11111111111111111111111111111111111111112'
NEW = 'A' * 44
FOREIGN = 'B' * 44


def account(owner, mint, raw, decimals=6):
    return {'account': {'data': {'parsed': {'info': {'owner': owner, 'mint': mint,
        'tokenAmount': {'amount': str(raw), 'decimals': decimals}}}}}}


class JupiterPortfolioTest(unittest.TestCase):
    def setUp(self):
        inventory._CACHE.clear()
        inventory._LOCKS.clear()
        inventory._JUPITER_CACHE.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.db = self.temp.name + '/data.sqlite'
        with sqlite3.connect(self.db) as con:
            con.executescript("CREATE TABLE users (id INTEGER, wallet_address TEXT);"
                              "CREATE TABLE user_tokens(user_id INTEGER, token_address TEXT,avg_price REAL);")
        self.jup_rows = [{'id': NEW, 'symbol': 'NEW', 'name': 'New Solana Token',
                          'usdPrice': 0.000001, 'icon': 'https://cdn.example.com/new.png'},
                         {'id': SOL, 'symbol': 'SOL', 'usdPrice': 100.0,
                          'icon': 'https://cdn.example.com/sol.png'}]
        self.dex_price = None
        self.calls = []
        def post(url, json, timeout):
            rows = [account('owner', NEW, 900000000000)] if json['params'][1]['programId'] == 'legacy' else []
            return SimpleNamespace(status_code=200, json=lambda: {'result': {'value': rows}})
        def get(url, timeout, headers):
            self.calls.append(url)
            return SimpleNamespace(status_code=200, json=lambda: self.jup_rows)
        def dex(url, timeout):
            rows = []
            if self.dex_price:
                rows = [{'chainId': 'solana', 'baseToken': {'address': NEW, 'symbol': 'DEX'},
                         'priceUsd': str(self.dex_price), 'liquidity': {'usd': 10000}}]
            return SimpleNamespace(status_code=200, json=lambda: {'pairs': rows})
        self.ctx = SimpleNamespace(DB_FILE=self.db, SOL_MINT=SOL,
            TOKEN_PROGRAM_ID='legacy', TOKEN_2022_PROGRAM_ID='new',
            SOLANA_RPC='primary', _PROXY_RPCS=[], _wallet_tokens_cache={},
            requests=SimpleNamespace(post=post, get=get), _dex_get=dex,
            _get_user_sol=lambda owner: 1, _sol_price_usd=100)
        inventory.install(self.ctx)

    def tearDown(self):
        self.temp.cleanup()

    def token(self):
        return next(t for t in inventory.fetch(self.ctx, 'login', 'owner')['tokens']
                    if t['mint'] == NEW)

    def test_jupiter_price_and_icon_for_new_mint(self):
        row = self.token()
        self.assertEqual(row['symbol'], 'NEW')
        self.assertEqual(row['logo_url'], 'https://cdn.example.com/new.png')
        self.assertAlmostEqual(row['price_usd'], 0.000001)
        self.assertAlmostEqual(row['value_usd'], 0.9)
        self.assertTrue(row['price_known'])
        self.assertGreaterEqual(len(self.calls), 1)

    def test_dex_price_kept_while_jupiter_supplies_missing_logo(self):
        self.dex_price = 0.000002
        row = self.token()
        self.assertEqual(row['symbol'], 'DEX')
        self.assertAlmostEqual(row['price_usd'], 0.000002)
        self.assertAlmostEqual(row['value_usd'], 1.8)
        self.assertEqual(row['logo_url'], 'https://cdn.example.com/new.png')

    def test_wrong_mint_cannot_supply_value_or_icon(self):
        self.jup_rows = [{'id': FOREIGN, 'symbol': 'NEW', 'usdPrice': 200.0,
                          'icon': 'https://cdn.example.com/wrong.png'}]
        row = self.token()
        self.assertFalse(row['price_known'])
        self.assertEqual(row['logo_url'], '')
        self.assertEqual(row['value_usd'], 0)

    def test_missing_api_response_never_creates_fake_price(self):
        self.jup_rows = []
        row = self.token()
        self.assertFalse(row['price_known'])
        self.assertEqual(row['symbol'], NEW[:6])
        self.assertEqual(row['price_usd'], 0)


if __name__ == '__main__':
    unittest.main()
