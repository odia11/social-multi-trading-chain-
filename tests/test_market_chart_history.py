"""Regression tests for free, durable Live Market candle history."""
import ast
import os
import sqlite3
import tempfile


ROOT = os.path.join(os.path.dirname(__file__), '..')
with open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8') as fh:
    SOURCE = fh.read()
TREE = ast.parse(SOURCE)

# GeckoTerminal's public Robinhood pages use /robinhood/pools/<address> and
# the OHLCV API uses the same network slug. Losing this mapping silently
# reduced every HOOD chart to locally observed candles only.
network_map = None
for node in TREE.body:
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == '_GECKOTERMINAL_NETWORK'
            for t in node.targets):
        network_map = ast.literal_eval(node.value)
assert network_map is not None
assert network_map['robinhood'] == 'robinhood'


def function_source(name):
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SOURCE, node)
    raise AssertionError(f'{name} not found')


with tempfile.TemporaryDirectory() as tmp:
    db_file = os.path.join(tmp, 'market.db')
    conn = sqlite3.connect(db_file)
    conn.execute('''CREATE TABLE market_candles_1m (
        chain TEXT NOT NULL, pair_address TEXT NOT NULL, bucket_ts INTEGER NOT NULL,
        open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
        samples INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(chain, pair_address, bucket_ts))''')
    conn.commit()
    conn.close()

    ns = {
        'sqlite3': sqlite3,
        'DB_FILE': db_file,
        '_MARKET_TF_SECONDS': {'1m': 60, '5m': 300, '15m': 900,
                               '1h': 3600, '4h': 14400, 'D': 86400},
    }
    for name in ('_store_observed_market_prices', '_stored_market_candles',
                 '_best_stored_market_candles'):
        exec(function_source(name), ns)

    store = ns['_store_observed_market_prices']
    best = ns['_best_stored_market_candles']
    pair = '0xAbCd'
    # Four real minute observations all fall inside one 5m bucket.
    store('robinhood', {pair: 1.00}, 60)
    store('robinhood', {pair: 1.05}, 120)
    store('robinhood', {pair: 0.98}, 180)
    store('robinhood', {pair: 1.10}, 240)

    candles, used = best('robinhood', pair, '5m')
    assert used == '1m', (used, candles)
    assert len(candles) == 4, candles
    assert [c['c'] for c in candles] == [1.00, 1.05, 0.98, 1.10]

    # Once two true 5m buckets exist, the requested resolution wins again.
    store('robinhood', {pair: 1.20}, 600)
    candles, used = best('robinhood', pair, '5m')
    assert used == '5m', (used, candles)
    assert len(candles) >= 2


with open(os.path.join(ROOT, 'static', 'live-market-pro.js'), encoding='utf-8') as fh:
    js = fh.read()
assert '_chartFetchQueue' in js
assert '2100-(Date.now()-_lastChartFetchAt)' in js
assert 'setInterval(function(){ chartTick(idx); }, 300000)' in js

print('market chart history tests passed')
