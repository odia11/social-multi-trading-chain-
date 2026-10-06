"""Price alert behavior, worker coordination and real Flask ownership boundaries."""
import concurrent.futures
import importlib.util
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import watchlist_alerts as w

MINT='So11111111111111111111111111111111111111112'
NOW=1780000000.0


class Alerts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.tmp.name)/'test.db')
        with sqlite3.connect(self.db) as c:
            c.executescript('''CREATE TABLE watchlist(user_id INTEGER,token_address TEXT,symbol TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(user_id,token_address));
            CREATE TABLE notifications(id INTEGER PRIMARY KEY,user_id INTEGER,type TEXT,content TEXT,link TEXT);''')
            c.executemany('INSERT INTO watchlist(user_id,token_address,symbol) VALUES(?,?,?)',[(1,MINT,'SOL'),(2,MINT,'SOL')])
        w.initialize(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_positive_finite_targets_only(self):
        for value in (None,True,False,[],{},'bad','NaN','inf',-1,0,1e-20,1e13):
            with self.assertRaises(ValueError):w.positive_price(value)
        self.assertEqual(w.positive_price('0.000001'),.000001)

    def test_create_requires_own_watchlist_and_direction(self):
        with self.assertRaises(ValueError):w.create_alert(self.db,3,MINT,'above',100,NOW)
        with self.assertRaises(ValueError):w.create_alert(self.db,1,MINT,'sideways',100,NOW)
        a=w.create_alert(self.db,1,MINT,'above',100,NOW)
        self.assertEqual(w.create_alert(self.db,1,MINT,'above',100,NOW),a)
        self.assertEqual(w.alert_list(self.db,2),[])

    def test_reached_once_and_receipt_opens_correct_token(self):
        aid=w.create_alert(self.db,1,MINT,'above',100,NOW)
        self.assertEqual(w.fire_prices(self.db,{MINT:99},NOW,NOW),[])
        fired=w.fire_prices(self.db,{MINT:100},NOW,NOW)
        self.assertEqual(len(fired),1)
        self.assertEqual(fired[0][1],aid)
        self.assertEqual(fired[0][3],'/live-market?mint='+MINT)
        self.assertEqual(w.fire_prices(self.db,{MINT:101},NOW,NOW),[])
        alert=w.alert_list(self.db,1)[0]
        self.assertFalse(alert['active']);self.assertEqual(alert['observed_price'],100)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT user_id,type FROM notifications').fetchall(),[(1,'price_alert')])

    def test_below_missing_stale_and_invalid_prices(self):
        w.create_alert(self.db,2,MINT,'below',90,NOW)
        for prices,at in [({},NOW),({MINT:float('nan')},NOW),({MINT:89},NOW-91),({MINT:89},NOW+1),({MINT:91},NOW)]:
            self.assertEqual(w.fire_prices(self.db,prices,at,NOW),[])
        self.assertEqual(len(w.fire_prices(self.db,{MINT:89},NOW,NOW)),1)

    def test_removed_token_does_not_fire_or_reappear(self):
        w.create_alert(self.db,1,MINT,'above',100,NOW)
        with sqlite3.connect(self.db) as c:c.execute('DELETE FROM watchlist WHERE user_id=1')
        self.assertEqual(w.alert_list(self.db,1),[])
        self.assertEqual(w.fire_prices(self.db,{MINT:101},NOW,NOW),[])
        self.assertEqual(w.claim_batch(self.db,NOW),[])

    def test_alert_cap_and_concurrent_delivery(self):
        for i in range(20):w.create_alert(self.db,1,MINT,'above',i+1,NOW)
        with self.assertRaises(ValueError):w.create_alert(self.db,1,MINT,'above',99,NOW)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:w.fire_prices(self.db,{MINT:100},NOW,NOW),range(4)))
        self.assertEqual(sum(map(len,results)),20)
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],20)

    def test_poll_claim_excludes_other_workers_and_rotates(self):
        with sqlite3.connect(self.db) as c:
            for i in range(65):
                mint=f'mint{i:02d}'
                c.execute('INSERT INTO watchlist(user_id,token_address,symbol) VALUES(1,?,?)',(mint,mint))
                c.execute('INSERT INTO watch_price_alerts(user_id,mint,direction,target,created_at) VALUES(1,?,"above",1,?)',(mint,NOW))
        first=w.claim_batch(self.db,NOW)
        self.assertEqual(len(first),30)
        self.assertEqual(w.claim_batch(self.db,NOW),[])
        second=w.claim_batch(self.db,NOW+60);third=w.claim_batch(self.db,NOW+120)
        self.assertEqual(len(set(first+second+third)),65)
        self.assertEqual(w.claim_batch(self.db,NOW+180),first)

    def test_poll_fresh_solana_highest_liquidity_only(self):
        w.create_alert(self.db,1,MINT,'above',100,NOW)
        url='https://api.dexscreener.com/latest/dex/tokens/'+MINT
        pushes=[]
        def pair(chain,liq,price):return dict(chainId=chain,liquidity={'usd':liq},priceUsd=price,baseToken={'address':MINT})
        response=SimpleNamespace(status_code=200,json=lambda:{'pairs':[pair('base',999999,999),pair('solana',1,999),pair('solana',10000,99)]})
        d=SimpleNamespace(DB_FILE=self.db,_dex_get=lambda *a,**k:response,_dex_resp_cache={url:(NOW,'')},_send_push_notification=lambda *a,**k:pushes.append(a),app=SimpleNamespace(logger=SimpleNamespace(warning=lambda *a:None)))
        with patch.object(w.time,'time',return_value=NOW):w.poll(d,NOW)
        self.assertEqual(pushes,[])
        response.json=lambda:{'pairs':[pair('solana',10000,101)]}
        d._dex_resp_cache[url]=(NOW+60,'')
        with patch.object(w.time,'time',return_value=NOW+60):w.poll(d,NOW+60)
        self.assertEqual(len(pushes),1)

    def test_stale_provider_cache_does_not_notify(self):
        w.create_alert(self.db,1,MINT,'above',100,NOW)
        response=SimpleNamespace(status_code=200,json=lambda:{'pairs':[dict(chainId='solana',liquidity={'usd':100},priceUsd=101,baseToken={'address':MINT})]})
        d=SimpleNamespace(DB_FILE=self.db,_dex_get=lambda *a,**k:response,_dex_resp_cache={},_send_push_notification=lambda *a,**k:self.fail('stale push'),app=SimpleNamespace(logger=SimpleNamespace(warning=lambda *a:None)))
        with patch.object(w.time,'time',return_value=NOW):w.poll(d,NOW)
        self.assertTrue(w.alert_list(self.db,1)[0]['active'])

    def test_migration_preserves_existing_data(self):
        w.create_alert(self.db,1,MINT,'above',100,NOW)
        w.initialize(self.db);w.initialize(self.db)
        self.assertEqual(len(w.alert_list(self.db,1)),1)


@unittest.skipUnless(importlib.util.find_spec('flask'), 'Flask dependencies required')
class Routes(unittest.TestCase):
    def setUp(self):
        Alerts.setUp(self)
        from flask import Flask,request,jsonify,make_response,render_template
        self.viewer=[1]
        app=Flask(__name__,template_folder=str(Path(__file__).resolve().parents[1]/'templates'))
        app.config['TESTING']=True
        app.jinja_env.globals.update(navbar_html=lambda _: '',app_version='test')
        def render(name,**kw):return make_response(render_template(name,**kw))
        def remove(token_address):
            with sqlite3.connect(self.db) as c:c.execute('DELETE FROM watchlist WHERE user_id=? AND token_address=?',(self.viewer[0],token_address))
            return jsonify(ok=True)
        app.add_url_rule('/api/watchlist/<token_address>',endpoint='api_watchlist_add',view_func=lambda token_address:jsonify(ok=True),methods=['POST'])
        app.add_url_rule('/api/watchlist/<token_address>',endpoint='api_watchlist_remove',view_func=remove,methods=['DELETE'])
        d=SimpleNamespace(app=app,DB_FILE=self.db,_authenticated_wallet=lambda:self.viewer[0],_get_uid=lambda c,w:w,
          _validate_csrf=lambda t:t=='valid',_get_csrf_token=lambda:'valid',_render_no_cache=render,
          is_valid_solana_address=lambda m:m==MINT,rate_limit=lambda *a:lambda f:f,_NAVBAR_MORE_LINKS=[])
        with patch.dict(w.os.environ,{'ORCAGENT_PRICE_ALERTS':'0'}):w.install(d)
        self.client=app.test_client()

    def tearDown(self):
        Alerts.tearDown(self)

    def test_authentication_csrf_and_owner(self):
        self.viewer[0]=None
        self.assertEqual(self.client.get('/api/price-alerts').status_code,401)
        self.assertEqual(self.client.get('/watchlist').status_code,302)
        self.viewer[0]=1
        body={'mint':MINT,'direction':'above','target':100,'user_id':2}
        self.assertEqual(self.client.post('/api/price-alerts',json=body).status_code,403)
        response=self.client.post('/api/price-alerts',json=body,headers={'X-CSRF-Token':'valid'})
        self.assertEqual(response.status_code,200)
        aid=response.json['id']
        self.viewer[0]=2
        self.assertEqual(self.client.get('/api/price-alerts?user_id=1').json['alerts'],[])
        self.assertEqual(self.client.delete('/api/price-alerts/'+str(aid),headers={'X-CSRF-Token':'valid'}).status_code,404)
        self.viewer[0]=1
        self.assertEqual(self.client.delete('/api/price-alerts/'+str(aid)).status_code,403)
        self.assertEqual(self.client.delete('/api/price-alerts/'+str(aid),headers={'X-CSRF-Token':'valid'}).status_code,200)

    def test_private_page_and_removal_cancels(self):
        response=self.client.get('/watchlist')
        self.assertEqual(response.status_code,302)
        self.assertTrue(response.location.endswith('/'))
        w.create_alert(self.db,1,MINT,'above',100)
        self.client.delete('/api/watchlist/'+MINT,headers={'X-CSRF-Token':'valid'})
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM watch_price_alerts').fetchone()[0],0)

    def test_malformed_body_and_target_rejected(self):
        headers={'X-CSRF-Token':'valid'}
        for body in [[],None,{'mint':'../bad'},dict(mint=MINT,direction='above',target='inf')]:
            self.assertEqual(self.client.post('/api/price-alerts',json=body,headers=headers).status_code,400)

    def test_watch_add_csrf_ownership_and_cap(self):
        path='/api/watchlist/'+MINT
        self.assertEqual(self.client.post(path,json={}).status_code,403)
        self.assertEqual(self.client.post(path,json={'user_id':2},headers={'X-CSRF-Token':'valid'}).status_code,200)
        with sqlite3.connect(self.db) as c:
            for i in range(99):c.execute('INSERT INTO watchlist(user_id,token_address,symbol) VALUES(1,?,?)',('test'+str(i),'T'))
            c.execute('DELETE FROM watchlist WHERE user_id=1 AND token_address=?',(MINT,))
            c.execute('INSERT INTO watchlist(user_id,token_address,symbol) VALUES(1,"other","O")')
        self.assertEqual(self.client.post(path,json={},headers={'X-CSRF-Token':'valid'}).status_code,400)


if __name__=='__main__':unittest.main()
