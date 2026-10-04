"""Discounts/signing/ledger tests with SQLite and fake execution; no live funds.

Uses unittest and the standard library, so it also runs without Flask or pytest.
"""
import ast
import contextlib
import datetime as dt
from decimal import Decimal
import io
from pathlib import Path
import re
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import trader_rewards as r

ROOT=Path(__file__).resolve().parents[1]


def signature(i):return str(i%9+1)*86+str((i//9)%9+1)


def functions(*names,namespace):
    tree=ast.parse((ROOT/'dashboard.py').read_text())
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(nodes)==len(names)
    for n in nodes:n.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'dashboard.py','exec'),namespace)
    return namespace


class Discounts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=str(Path(self.temp.name)/'fees.sqlite')
        self.now=time.time()
        old=dt.datetime.fromtimestamp(self.now-20*86400,dt.timezone.utc).isoformat()
        with sqlite3.connect(self.db) as c:
            c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,created_at TEXT,referred_by TEXT,username TEXT);
                CREATE TABLE fees(id INTEGER PRIMARY KEY,user_wallet TEXT,token TEXT,gross_profit REAL,fee_amount REAL,fee_tx TEXT,status TEXT,kind TEXT,recipient TEXT);''')
            c.executemany('INSERT INTO users VALUES(?,?,?,NULL,?)',[(1,'alice',old,'Alice'),(2,'bob',old,'Bob')])
        r.initialize(self.db)

    def tearDown(self):self.temp.cleanup()

    def pro(self):
        for i in range(7):
            self.assertTrue(r.record_confirmed_trade(self.db,'alice',signature(i),'mint'+str(i),'buy',400,'USDC',0,self.now-i*86400))
        self.assertEqual(r.progress(self.db,'alice',self.now)['status'],'Pro Trader')

    def test_server_status_earns_and_expires_discount(self):
        self.assertEqual(r.manual_trade_fee_bps(self.db,'alice',self.now),75)
        self.pro()
        self.assertEqual(r.manual_trade_fee_bps(self.db,'alice',self.now),70)
        self.assertEqual(r.manual_trade_fee_bps(self.db,'bob',self.now),75)
        self.assertEqual(r.manual_trade_fee_bps(self.db,'alice',self.now+31*86400),75)
        self.assertEqual(r.manual_trade_fee_bps(self.db,'missing',self.now),75)
        with patch('trader_rewards.progress',side_effect=sqlite3.OperationalError('unavailable')):
            self.assertEqual(r.manual_trade_fee_bps(self.db,'alice',self.now),75)

    def test_reviewed_or_excluded_volume_does_not_unlock_discount(self):
        self.pro()
        with sqlite3.connect(self.db) as c:c.execute("UPDATE reward_trades SET eligibility='review'")
        self.assertEqual(r.manual_trade_fee_bps(self.db,'alice',self.now),75)
        with sqlite3.connect(self.db) as c:c.execute("UPDATE reward_trades SET eligibility='excluded'")
        self.assertEqual(r.manual_trade_fee_bps(self.db,'alice',self.now),75)

    def test_fee_ceiling_and_invalid_client_rates(self):
        self.assertTrue(r.validate_fee_ceiling(70,70))
        self.assertTrue(r.validate_fee_ceiling(None,70))
        self.assertFalse(r.validate_fee_ceiling(70,75))
        for value in (True,False,'70',70.0,-1,76,float('nan')):
            with self.assertRaises(ValueError):r.validate_fee_ceiling(value,75)

    def execution(self,stdout,code=0,rate=None,action='buy'):
        ns=dict(os=os,sys=sys,re=re,subprocess=subprocess,BASE='.',DB_FILE=self.db,FEE_RATE_TXN=.0075,
            _sol_price_usd=100,get_user_state=lambda wallet:{'positions':{}},
            _ensure_solana_gas=lambda *args,**kwargs:(True,''),_sol_fee_recipient=lambda:'recipient',
            _ext_hit=lambda *args:None,add_user_log=lambda *args:None,_redact_keys=lambda text:text)
        functions('_execute_user_swap_ex','_parse_swap_realized_amounts','_validated_execution_fee_rate',namespace=ns)
        captured={}
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=code,stdout=stdout,stderr='')) as run:
            answer=ns['_execute_user_swap_ex']('alice','fake',action,'mint','0.52',capture=captured,fee_rate=rate)
        return answer,captured,run

    def test_rate_is_bound_to_signed_execution_and_savings(self):
        output=f'[fee] buy: requesting quote\nBUY mint 0.52 SOL got:20 sol:0.52 fee_base:0.50 TX:{signature(8)}'
        result,captured,run=self.execution(output,rate=.007)
        self.assertTrue(result[0]);self.assertTrue(captured['fee_bundled'])
        self.assertEqual(captured['fee_rate'],.007)
        self.assertEqual(run.call_args.kwargs['env']['FEE_RATE_TXN'],'0.007')
        benefit=r.benefits(self.db,'alice',self.now)
        self.assertEqual(benefit['saved_fees_usdc'],'0.02') # 0.5 SOL × 5bps × $100 = $0.025, rounded down
        self.assertEqual(r.benefits(self.db,'bob',self.now)['saved_fees_usdc'],'0.00')
        self.assertFalse(benefit['cash_payout'])
        self.execution(output,rate=.007)
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM reward_fee_discounts').fetchone()[0],1)

    def test_sell_discount_uses_net_fill_and_same_gross_fee_basis(self):
        output=f'[fee] sell: requesting 70 bps platform fee)\nSELL mint amt:20 sol:0.993 TX:{signature(8)}'
        result,captured,run=self.execution(output,rate=.007,action='sell')
        self.assertTrue(result[0]);self.assertTrue(captured['fee_bundled'])
        self.assertEqual(captured['fee_rate'],.007)
        self.assertEqual(r.benefits(self.db,'alice',self.now)['saved_fees_usdc'],'0.05')

    def test_normal_automated_fee_is_unchanged(self):
        output=f'[fee] buy: requesting quote\nBUY mint 0.52 SOL got:20 sol:0.52 fee_base:0.50 TX:{signature(8)}'
        result,captured,run=self.execution(output)
        self.assertTrue(result[0]);self.assertEqual(captured['fee_rate'],.0075)
        self.assertEqual(run.call_args.kwargs['env']['FEE_RATE_TXN'],'0.0075')
        self.assertEqual(r.benefits(self.db,'alice',self.now)['saved_fees_usdc'],'0.00')

    def test_failed_or_fee_less_execution_earns_no_savings(self):
        for output,code in ((f'BUY mint 0.52 SOL got:20 sol:0.52 fee_base:0.50 TX:{signature(8)}',0),
                            (f'[fee] buy: requesting quote\nBUY mint 0.52 SOL got:20 sol:0.52 fee_base:0.50 TX:{signature(8)}',1)):
            self.execution(output,code,.007)
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM reward_fee_discounts').fetchone()[0],0)
        result,capture,run=self.execution('not executed',rate=0)
        self.assertFalse(result[0]);run.assert_not_called()

    def test_fee_record_matches_rate_used_by_transaction(self):
        ns=dict(sqlite3=sqlite3,DB_FILE=self.db,FEE_RATE_TXN=.0075,Decimal=Decimal,
                _sol_fee_recipient=lambda:'recipient')
        functions('_validated_execution_fee_rate','_charge_txn_fee',namespace=ns)
        with contextlib.redirect_stdout(io.StringIO()):
            ns['_charge_txn_fee']('fake','alice',1,'TOKEN',1.000000019,'buy',bundled=True,applied_fee_rate=.007)
        with sqlite3.connect(self.db) as c:
            row=c.execute('SELECT fee_amount,status,fee_tx FROM fees').fetchone()
        self.assertEqual(row,(.007,'ok','bundled-in-swap'))

    def test_recorded_savings_follow_token_precision_and_do_not_create_cash(self):
        self.assertTrue(r.record_fee_discount(self.db,'alice',signature(8),1.000000019,'SOL',70,100))
        with sqlite3.connect(self.db) as c:
            row=c.execute('SELECT saved_base FROM reward_fee_discounts').fetchone()
            self.assertEqual(Decimal(row[0]),Decimal('0.0005'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM fees').fetchone()[0],0)
        for rate in (75,0,-70,100):self.assertFalse(r.record_fee_discount(self.db,'alice',signature(9),1,'SOL',rate,100))
        for value in ('NaN','Infinity','-1','0'):self.assertFalse(r.record_fee_discount(self.db,'alice',signature(9),value,'SOL',70,100))

    def test_upgrade_preserves_existing_activity(self):
        self.pro();r.initialize(self.db)
        self.assertEqual(r.progress(self.db,'alice',self.now)['trades'],7)
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],2)

    def test_stale_discount_is_rejected_before_wallet_or_swap_access(self):
        data={'max_platform_fee_bps':70,'is_pro':True,'wallet':'alice'}
        ns=dict(request=SimpleNamespace(method='POST',is_json=True,get_json=lambda **kwargs:data),
                _authenticated_wallet=lambda:'bob',_live_market_fee_rate=lambda wallet:.0075,
                jsonify=lambda value:value,traceback=SimpleNamespace(print_exc=lambda:None),
                _server_error_msg=lambda *args:'unexpected')
        functions('api_instant_trade',namespace=ns)
        response,status=ns['api_instant_trade']()
        self.assertEqual(status,409);self.assertTrue(response['fee_changed'])
        data['max_platform_fee_bps']='70'
        response,status=ns['api_instant_trade']()
        self.assertEqual(status,400)
        self.assertEqual(response['error'],'Invalid maximum platform fee')


if __name__=='__main__':unittest.main()
