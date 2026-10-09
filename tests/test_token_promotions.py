"""Promotion scheduling, isolation, real payment verification, and view receipts."""
import concurrent.futures
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from flask import Flask, jsonify, request, session
import requests
import token_promotions as promo

MINT='So11111111111111111111111111111111111111112'
WALLET='11111111111111111111111111111111'

class Promotions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'test.db')
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE promotions(id INTEGER PRIMARY KEY,tx_signature TEXT)')
        # No legacy rows in this reduced app. Actual-schema migration has its own test.
        self.app=Flask(__name__);self.app.secret_key='test-only-session-key';self.app.testing=True
        for endpoint,rule in [('api_promote_create','/api/promote/create'),('api_promote_submit_tx','/api/promote/<int:promotion_id>/submit-tx'),('api_promote_status','/api/promote/<int:promotion_id>/status'),('api_promote_simulate_confirm','/api/promote/<int:promotion_id>/simulate-confirm'),('api_promote_featured','/api/promote/featured')]:
            self.app.add_url_rule(rule,endpoint,lambda **kw:None,methods=['GET','POST'])
        self.app.add_url_rule('/api/token/info/<mint>', 'api_token_info',lambda mint:jsonify(ok=True,symbol='TEST',name='Test token',address=mint,chain='solana'))
        self.d=SimpleNamespace(app=self.app,DB_FILE=self.path,ADMIN_WALLET=MINT,_sol_price_usd=100,
            _authenticated_wallet=lambda:session.get('wallet'),_validate_csrf=lambda value:value=='csrf',
            is_valid_solana_address=lambda value:isinstance(value,str) and len(value)>30,
            rate_limit=lambda *a:lambda f:f,_get_trading_wallet_address=lambda wallet:MINT,
            requests=requests,_PROXY_RPCS=['mock-rpc'])
        with patch.object(threading.Thread,'start'):
            promo.install(self.d)
        self.client=self.app.test_client()
        self.login(self.client,WALLET)

    def tearDown(self):self.tmp.cleanup()
    def login(self,client,wallet):
        with client.session_transaction() as s:s['wallet']=wallet
    def create(self,package='spotlight',client=None):
        return (client or self.client).post('/api/promote/create',json=dict(package=package,token_mint=MINT,description='My project',payment_method='external'),headers={'X-CSRF-Token':'csrf'})
    def confirm(self,identifier,signature=None):
        signature=signature or 'A'*64+str(identifier)
        # Use valid base58 ending avoiding digit zero.
        alphabet='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
        signature='A'*64+alphabet[identifier%58]+alphabet[identifier//58]
        r=self.client.post(f'/api/promote/{identifier}/submit-tx',json={'tx_signature':signature},headers={'X-CSRF-Token':'csrf'})
        self.assertEqual(r.status_code,200,r.json)
        with patch.object(promo,'verify_payment',return_value=True):
            self.client.get(f'/api/promote/{identifier}/status')
        return signature

    def test_fifty_requests_reserve_capacity_and_round_robin(self):
        identifiers=[]
        for i in range(50):
            self.login(self.client,'wallet-'+str(i));r=self.create();self.assertEqual(r.status_code,200,r.json)
            identifiers.append(r.json['promotion_id']);self.confirm(identifiers[-1])
        with promo.connection(self.path) as db:
            rows=db.execute('SELECT starts,ends FROM promotion_campaigns').fetchall()
            for t in sorted({r['starts'] for r in rows}):
                self.assertLessEqual(sum(r['starts']<=t<r['ends'] for r in rows),10)
            self.assertEqual(len({r['starts']//3600 for r in rows}),5)
        selections=[]
        for i in range(20):
            selections += [p['id'] for p in self.client.get('/api/promote/featured?placement=feed').json['promotions']]
        self.assertEqual(len(set(selections)),10)
        self.assertEqual(set(selections.count(x) for x in set(selections)),{2})

    def test_scheduler_checks_middle_overlap_and_all_placements(self):
        now=int(time.time());r=self.create('premium');self.assertEqual(r.status_code,200)
        with promo.connection(self.path,True) as db:
            db.execute("DELETE FROM promotion_slots");db.execute('DELETE FROM promotion_campaigns')
            for i in range(5):
                db.execute('''INSERT INTO promotion_campaigns (wallet,mint,symbol,name,description,website,social,package,price_usd,lamports,payer,treasury,created,quote_until,starts,ends,status)
                    VALUES('w','m','s','n','','','','premium',50,1,'w','t',?,?,?,?, 'confirmed')''',(now,now+600,now+100,now+200))
                db.execute('INSERT INTO promotion_slots(campaign,placement) VALUES(?,?)',(i+1,'banner'))
            start,end=promo.next_slot(db,['feed','market','banner'],300,now)
            self.assertEqual(start,now+200)
            self.assertEqual(end,start+300)

    def test_owner_csrf_and_signature_replay(self):
        self.assertEqual(self.client.post('/api/promote/create',json={}).status_code,403)
        identifier=self.create().json['promotion_id'];sig=self.confirm(identifier)
        other=self.create().json['promotion_id']
        r=self.client.post(f'/api/promote/{other}/submit-tx',json={'tx_signature':sig},headers={'X-CSRF-Token':'csrf'})
        self.assertEqual(r.status_code,409)
        stranger=self.app.test_client();self.login(stranger,'stranger')
        self.assertEqual(stranger.get(f'/api/promote/{identifier}/status').status_code,404)
        self.assertEqual(stranger.get('/api/promote/mine').json['campaigns'],[])
        self.assertEqual(self.client.post(f'/api/promote/{identifier}/simulate-confirm',headers={'X-CSRF-Token':'csrf'}).status_code,403)

    def test_only_receipted_visible_events_count_once(self):
        identifier=self.create().json['promotion_id'];self.confirm(identifier)
        ad=self.client.get('/api/promote/featured?placement=feed').json['promotions'][0]
        payload={'receipt':ad['receipt'],'event':'view'}
        foreign=self.app.test_client()
        self.assertEqual(foreign.post('/api/promote/event',json=payload).status_code,404)
        for _ in range(3):self.assertEqual(self.client.post('/api/promote/event',json=payload).status_code,200)
        for _ in range(3):self.client.post('/api/promote/event',json={**payload,'event':'click'})
        stats=self.client.get('/api/promote/mine').json['campaigns'][0]
        self.assertEqual((stats['views'],stats['unique_viewers'],stats['clicks']),(1,1,1))
        self.assertEqual(stats['ctr'],100)
        self.assertEqual(len(stats['click_history']),1)

    def test_expired_quotes_release_slots_and_delayed_confirmation_rebooks(self):
        now=int(time.time())
        ids=[]
        for i in range(10):
            self.login(self.client,'wallet-'+str(i));ids.append(self.create().json['promotion_id'])
        with promo.connection(self.path,True) as db:db.execute('UPDATE promotion_campaigns SET quote_until=?',(now-1,))
        self.login(self.client,'buyer')
        new=self.create();self.assertLessEqual(new.json['starts'],now+2)
        self.confirm(new.json['promotion_id'])
        with promo.connection(self.path,True) as db:
            db.execute('UPDATE promotion_campaigns SET starts=?,ends=? WHERE id=?',(now-3600,now+23*3600,ids[0]))
        self.login(self.client,'wallet-0');self.confirm(ids[0])
        with promo.connection(self.path) as db:
            row=db.execute('SELECT * FROM promotion_campaigns WHERE id=?',(ids[0],)).fetchone()
            self.assertGreaterEqual(row['starts'],now)
            self.assertEqual(row['ends']-row['starts'],86400)

    def test_invalid_price_links_and_injected_token_metadata(self):
        self.d._sol_price_usd=float('nan');self.assertEqual(self.create().status_code,503)
        self.d._sol_price_usd=100
        r=self.client.post('/api/promote/create',json=dict(package='basic',token_mint=MINT,description='Project',website='javascript:alert(1)',token_symbol='FAKE'),headers={'X-CSRF-Token':'csrf'})
        self.assertEqual(r.status_code,400)
        r=self.create('basic');self.assertEqual(r.json['lamports'],100000000)
        row=self.client.get('/api/promote/mine').json['campaigns'][0];self.assertEqual(row['symbol'],'TEST')
        self.assertNotIn('wallet',row)
        self.assertNotIn('payer',self.client.get('/api/promote/directory').json)

    def test_atomic_concurrent_slot_reservations(self):
        def reserve(i):
            c=self.app.test_client();self.login(c,'parallel-'+str(i));return self.create(client=c).json
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            replies=list(pool.map(reserve,range(50)))
        self.assertTrue(all(r['ok'] for r in replies))
        for t in {r['starts'] for r in replies}:
            self.assertLessEqual(sum(r['starts']<=t<r['ends'] for r in replies),10)

    def test_designated_wallet_public_demo_without_balance_price_or_paid_inventory(self):
        payload=dict(package='premium',token_mint=MINT,description='Demo test',demo=True,payment_method='trading')
        self.assertEqual(self.client.post('/api/promote/create',json=payload,headers={'X-CSRF-Token':'csrf'}).status_code,403)
        self.login(self.client,promo.DEMO_WALLET)
        self.d._sol_price_usd=0
        self.d._get_trading_wallet_address=lambda wallet:None
        self.assertTrue(self.client.get('/api/promote/packages').json['can_demo'])
        ids=[]
        for i in range(15):
            r=self.client.post('/api/promote/create',json=payload,headers={'X-CSRF-Token':'csrf'})
            self.assertEqual(r.status_code,200,r.json)
            self.assertEqual(r.json['lamports'],0)
            ids.append(r.json['promotion_id'])
            self.assertEqual(self.client.post(f'/api/promote/{ids[-1]}/simulate-confirm',json={},headers={'X-CSRF-Token':'csrf'}).status_code,200)
            self.assertEqual(self.client.post(f'/api/promote/{ids[-1]}/simulate-confirm',json={},headers={'X-CSRF-Token':'csrf'}).status_code,200)
        visitor=self.app.test_client()
        directory=visitor.get('/api/promote/directory').json['campaigns']
        self.assertEqual(len(directory),15)
        self.assertTrue(all(c['demo'] for c in directory))
        for place in promo.CAPACITY:
            ads=visitor.get('/api/promote/featured?placement='+place).json['promotions']
            self.assertEqual(len(ads),3 if place=='market' else 1)
            self.assertTrue(all(c['demo'] for c in ads))
        receipt=ads[0]['receipt']
        self.assertEqual(visitor.post('/api/promote/event',json={'receipt':receipt,'event':'view'}).status_code,200)
        self.assertEqual(visitor.post('/api/promote/event',json={'receipt':receipt,'event':'click'}).status_code,200)
        self.assertTrue(all(c['status']=='demo_active' for c in self.client.get('/api/promote/mine').json['campaigns']))
        with promo.connection(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM promotion_used_payments').fetchone()[0],0)
            now=int(time.time())
            self.assertEqual(promo.next_slot(db,['feed','market','banner'],86400,now)[0],now)
        self.d._sol_price_usd=100
        paid=self.create().json['promotion_id']
        with promo.connection(self.path,True) as db:
            db.execute("UPDATE promotion_campaigns SET status='confirmed',confirmed=? WHERE id=?",(int(time.time()),paid))
        selected=visitor.get('/api/promote/featured?placement=feed').json['promotions']
        self.assertEqual(selected[0]['id'],paid)
        self.assertFalse(selected[0]['demo'])
        with promo.connection(self.path,True) as db:
            db.execute("UPDATE promotion_campaigns SET ends=0 WHERE status='demo_active'")
        self.assertFalse(any(c['demo'] for c in visitor.get('/api/promote/directory').json['campaigns']))
        self.assertEqual(visitor.get('/api/promote/featured?placement=banner').json['promotions'],[])
        self.assertEqual(self.client.post(f'/api/promote/{paid}/simulate-confirm',json={},headers={'X-CSRF-Token':'csrf'}).status_code,403)
        self.login(self.client,'stranger')
        self.assertEqual(self.client.post(f'/api/promote/{ids[0]}/simulate-confirm',json={},headers={'X-CSRF-Token':'csrf'}).status_code,403)

    def test_exact_finalized_signer_and_transfer(self):
        identifier=self.create().json['promotion_id']
        with promo.connection(self.path) as db:row=dict(db.execute('SELECT * FROM promotion_campaigns WHERE id=?',(identifier,)).fetchone())
        row['signature']='A'*64
        tx={'blockTime':row['created'],'meta':{'err':None},'transaction':{'message':{
            'accountKeys':[{'pubkey':WALLET,'signer':True}],
            'instructions':[{'program':'system','parsed':{'type':'transfer','info':{'source':WALLET,'destination':MINT,'lamports':row['lamports']}}}]}}}
        def verify():
            with patch.object(requests,'post',return_value=SimpleNamespace(json=lambda:{'result':tx})) as rpc:
                value=promo.verify_payment(self.d,row)
                self.assertEqual(rpc.call_args.kwargs['json']['params'][1]['commitment'],'finalized')
                return value
        self.assertTrue(verify())
        ix=tx['transaction']['message']['instructions'][0]['parsed']['info'];ix['lamports']-=1;self.assertFalse(verify());ix['lamports']+=1
        tx['transaction']['message']['accountKeys'][0]['signer']=False;self.assertFalse(verify())
        tx['transaction']['message']['accountKeys'][0]['signer']=True;tx['blockTime']=row['created']-60;self.assertFalse(verify())
        tx['blockTime']=row['created'];tx['meta']['err']={};self.assertFalse(verify())

class LegacyMigration(unittest.TestCase):
    def test_existing_paid_placements_and_ids_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=str(Path(tmp)/'db')
            with sqlite3.connect(path) as db:
                db.execute('''CREATE TABLE promotions(id INTEGER PRIMARY KEY,wallet TEXT,token_mint TEXT,token_symbol TEXT,token_name TEXT,amount_sol REAL,created_at TEXT,confirmed_at TEXT,expires_at TEXT,status TEXT,tx_signature TEXT,show_in_feed INTEGER,show_in_market INTEGER,show_in_traders INTEGER)''')
                db.execute("INSERT INTO promotions VALUES(5,'w','m','T','Token',.1,'2026-10-09 00:00:00','2026-10-09 01:00:00','2026-10-10 01:00:00','confirmed','sig',1,0,1)")
            promo.initialize(path);promo.initialize(path)
            with promo.connection(path) as db:
                row=db.execute('SELECT * FROM promotion_campaigns').fetchone()
                self.assertEqual(row['id'],5);self.assertEqual(row['ends']-row['starts'],86400)
                self.assertEqual(row['signature'],'sig')
                self.assertEqual([r[0] for r in db.execute('SELECT placement FROM promotion_slots ORDER BY placement')],['feed','traders'])

if __name__=='__main__':unittest.main()
