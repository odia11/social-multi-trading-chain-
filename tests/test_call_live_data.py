"""Live call endpoint regressions without starting trading threads or making requests."""
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from flask import Flask
import requests
from call_live_data import install, record_quote, select_quote

MINT = 'A' * 32

def pair(price, cap, liquidity=100, mint=MINT, chain='solana'):
    return dict(baseToken={'address':mint}, chainId=chain, priceUsd=price,
                marketCap=cap, liquidity={'usd':liquidity})

class LiveCalls(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'calls.db')
        with sqlite3.connect(self.path) as c:
            c.execute('''CREATE TABLE token_calls (id INTEGER PRIMARY KEY, mint TEXT, chain TEXT,
                      price_at_call REAL, mcap_at_call REAL, peak_price REAL, last_price REAL, peak_at TEXT, timestamp TEXT DEFAULT CURRENT_TIMESTAMP)''')
            c.execute('INSERT INTO token_calls (id,mint,chain,price_at_call,mcap_at_call,peak_price,last_price) VALUES (1,?,"solana",1,100,1,1)', (MINT,))
        self.http = SimpleNamespace(get=Mock(), RequestException=requests.RequestException)
        self.d = SimpleNamespace(app=Flask(__name__), DB_FILE=self.path, requests=self.http,
            _DEX_HEADERS={}, is_valid_solana_address=lambda m:len(m)==32,
            rate_limit=lambda *a:lambda f:f)
        install(self.d)
        self.client = self.d.app.test_client()
        self.http.get.return_value = SimpleNamespace(status_code=200,json=lambda:{'pairs':[pair(2,220)]})
    def tearDown(self):
        self.tmp.cleanup()
    def get(self):
        return self.client.get('/api/calls/live?ids=1')
    def expire(self):
        with sqlite3.connect(self.path) as c:
            c.execute('UPDATE token_calls SET quote_at=?', (time.time()-40,))
    def test_refresh_and_drop_preserve_entry_and_peak(self):
        first = self.get().json['calls'][0]
        self.assertEqual((first['last_price'], first['mcap_now'],first['multiplier']), (2,220,2))
        self.assertFalse(first['stale'])
        self.expire()
        self.d.app=Flask("drop");install(self.d);self.client=self.d.app.test_client()
        self.http.get.return_value.json=lambda:{'pairs':[pair(.5,55)]}
        second = self.get().json['calls'][0]
        self.assertEqual((second['price_at_call'],second['mcap_at_call']), (1,100))
        self.assertEqual((second['last_price'],second['peak_price'],second['mcap_peak']), (.5,2,220))
    def test_failure_keeps_values_marks_stale(self):
        self.get();self.expire()
        # A new installer models a later retry beyond the attempt debounce.
        self.d.app=Flask("retry");install(self.d);self.client=self.d.app.test_client()
        self.http.get.side_effect=requests.RequestException('offline')
        response=self.get()
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertTrue(response.json['calls'][0]['stale'])
        self.assertEqual(response.json['calls'][0]['last_price'],2)
    def test_repeated_read_coalesces_and_restart_retains_peak(self):
        self.get();self.get()
        self.assertEqual(self.http.get.call_count,1)
        app=Flask('restart');self.d.app=app;install(self.d)
        self.assertEqual(app.test_client().get('/api/calls/live?ids=1').json['calls'][0]['peak_price'],2)
    def test_old_background_result_cannot_replace_newer(self):
        self.get()
        with sqlite3.connect(self.path) as c:
            record_quote(c,MINT,{'price':99,'mcap':9900},time.time()-120)
        self.assertEqual(self.get().json['calls'][0]['peak_price'],2)
    def test_exact_mint_chain_deepest_valid_pool(self):
        found=select_quote([pair(99,9900,999,mint=MINT.lower()),pair(99,9900,999,chain='base'),
                            pair(99,9900,1),pair(2,220,100),pair('nan',99,1000)],MINT)
        self.assertEqual(found,{'price':2,'mcap':220})
    def test_cached_quote_before_call_does_not_rewrite_entry_period(self):
        with sqlite3.connect(self.path) as c:
            record_quote(c,MINT,{'price':99,'mcap':9900},time.time()-120)
        self.assertEqual(self.get().json['calls'][0]['peak_price'],2)
    def test_bounded_request(self):
        self.assertEqual(self.client.get('/api/calls/live?ids=x').status_code,400)
        self.assertEqual(self.client.get('/api/calls/live?ids='+','.join(['1']*31)).status_code,400)
    def test_missing_cap_is_not_invented(self):
        self.http.get.return_value.json=lambda:{'pairs':[pair(2,0)]}
        self.assertIsNone(self.get().json['calls'][0]['mcap_now'])

if __name__=='__main__':unittest.main()
