"""No conversation quota, scoped continuations and independent fresh native quotes."""
import datetime as dt
import sqlite3
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import requests
import platform_prices as prices
import platform_assistant as agent
import test_platform_assistant as fixtures

def reply(body,status=200):
    return SimpleNamespace(status_code=status,json=lambda:body)

class Providers(unittest.TestCase):
    def setUp(self):
        prices._CACHE.clear();prices._CALLS.clear()
    def test_rate_limited_primary_uses_fresh_native_exchange_price(self):
        q=prices.query('SOL and BTC price in EUR?');called=[]
        def get(url,**kwargs):
            called.append(url)
            if 'coingecko' in url:return reply({},429)
            stamp=dt.datetime.now(dt.timezone.utc).isoformat()
            return reply(dict(price='120' if 'SOL-' in url else '85000',time=stamp))
        snap=prices.fetch(q,get=get)
        self.assertEqual(snap['source'],'Coinbase')
        self.assertEqual([r['symbol'] for r in snap['rows']],['SOL','BTC'])
        self.assertEqual(snap['currency'],'eur')
        self.assertEqual(len(called),3)
        self.assertIn('EUR',prices.render(q,snap)[1])
    def test_timeout_on_primary_does_not_prevent_fallback(self):
        def get(url,**kwargs):
            if 'coingecko' in url:raise requests.Timeout()
            return reply(dict(price='120',time=dt.datetime.now(dt.timezone.utc).isoformat()))
        snap=prices.fetch(prices.query('SOL price'),get=get)
        self.assertEqual(snap['source'],'Coinbase')
    def test_stale_primary_and_stale_fallback_never_claim_current(self):
        old=time.time()-300
        def get(url,**kwargs):
            if 'coingecko' in url:return reply({'solana':{'usd':100,'last_updated_at':old}})
            return reply(dict(price='110',time=dt.datetime.fromtimestamp(old,dt.timezone.utc).isoformat()))
        q=prices.query('SOL price');self.assertIsNone(prices.fetch(q,get=get))
        self.assertEqual(prices.render(q,None)[1],prices.UNAVAILABLE)
    def test_cache_age_expiry_forces_refresh_even_before_cache_ttl(self):
        q=prices.query('SOL price')
        key=repr(sorted(q.items()))
        prices._CACHE[key]=(time.time(),30,dict(kind='prices',rows=[dict(symbol='SOL',price=1,observed=time.time()-121)],currency='usd',source='CoinGecko'))
        def get(url,**kwargs):
            if 'coingecko' in url:return reply({'solana':{'usd':120,'last_updated_at':time.time()}})
            self.fail('valid primary should need no fallback')
        self.assertEqual(prices.fetch(q,get=get)['rows'][0]['price'],120)

class Conversations(unittest.TestCase):
    setUp=fixtures.Assistant.setUp
    tearDown=fixtures.Assistant.tearDown
    source=fixtures.Assistant.source
    def nested(self,message,parent,uid=2):
        rid=self.source(message,uid)
        with sqlite3.connect(self.db) as c:
            c.execute('UPDATE feed_replies SET parent_reply_id=? WHERE id=?',(parent,rid))
        return rid
    def test_no_user_or_global_daily_or_short_window_reply_limit(self):
        with sqlite3.connect(self.db) as c:
            for i in range(1000):
                c.execute('INSERT INTO platform_assistant_events VALUES(?,?,?,?,?,?,?)',
                          ('old:'+str(i),'reply',2 if i<150 else 99,'p1',None,'wallet',self.now))
        for _ in range(20):
            self.assertIsNotNone(agent.reply_to(self.d,self.source('@orcagent hi'),'member',self.now))
    def test_direct_followup_without_tag_gets_price_response(self):
        first=self.source('@orcagent how are you?')
        bot=agent.reply_to(self.d,first,'member',self.now)
        follow=self.nested('What is the price of $BTC?',bot)
        snap=dict(kind='prices',rows=[dict(symbol='BTC',price=85000,observed=time.time())],currency='usd',source='Coinbase')
        with patch.object(prices,'fetch',return_value=snap) as fetch:
            rid=agent.reply_to(self.d,follow,'member',self.now+1)
        self.assertIsNotNone(rid);fetch.assert_called_once()
        with sqlite3.connect(self.db) as c:
            message=c.execute('SELECT message FROM feed_replies WHERE id=?',(rid,)).fetchone()[0]
        self.assertIn('BTC: 85,000.00 USD',message)
    def test_followups_do_not_capture_other_users_unrelated_or_expired_threads(self):
        first=self.source('@orcagent hi');bot=agent.reply_to(self.d,first,'member',self.now)
        with sqlite3.connect(self.db) as c:c.execute("INSERT INTO users VALUES(3,'other','Other',0)")
        other=self.nested('BTC price?',bot,uid=3)
        with patch.object(prices,'fetch',side_effect=AssertionError('must not fetch')):
            self.assertIsNone(agent.reply_to(self.d,other,'other',self.now+1))
            self.assertIsNone(agent.reply_to(self.d,self.source('BTC price?'),'member',self.now+1))
            expired=self.nested('BTC price?',bot)
            self.assertIsNone(agent.reply_to(self.d,expired,'member',self.now+3601))
    def test_duplicate_followup_publishes_only_one_reply(self):
        bot=agent.reply_to(self.d,self.source('@orcagent hi'),'member',self.now)
        follow=self.nested('How do I sell?',bot)
        self.assertIsNotNone(agent.reply_to(self.d,follow,'member',self.now+1))
        self.assertIsNone(agent.reply_to(self.d,follow,'member',self.now+1))

if __name__=='__main__':unittest.main()
