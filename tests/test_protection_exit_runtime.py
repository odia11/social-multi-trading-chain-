"""Execute production exit functions against mocked prices/swaps; no transactions."""
import ast
import contextlib
import copy
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

import protection_exits as p

TREE = ast.parse(Path('dashboard.py').read_text())


def functions(ns, *names):
    for name in names:
        node = next(n for n in ast.walk(TREE) if isinstance(n,ast.FunctionDef) and n.name == name)
        exec(compile(ast.Module(body=[copy.deepcopy(node)],type_ignores=[]),'dashboard.py','exec'), ns)


def eventually(predicate, timeout=2):
    until = time.monotonic()+timeout
    while time.monotonic()<until:
        if predicate():
            return True
        time.sleep(.01)
    return False


class ProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name,'test.db')
        self.market = {}
        self.us = {'positions':{}}
        self.calls = []
        self.release = threading.Event()
        self.release.set()
        self.fail = False
        self.ns = dict(DB_FILE=self.db,user_id=1,wallet='WalletCase',us=self.us,
            positions=self.us['positions'],stop_event=threading.Event(),short='WalletCase',
            _enc_blob='ciphertext',_enc_blob_evm=None,pref_notifications=False,
            stop_loss=.08,take_profit=.18,tiered_tp_enabled=False,_sol_price_usd=100,
            _EXIT_TD_PRICE_MAX_AGE=3,_exit_td_at={},EXIT_NO_PRICE_ALERT_SEC=20,
            EXIT_SELL_FAIL_ALERT=5,STOP_LOSS=.08,TAKE_PROFIT=.18,
            _protection_price=p.market_price,_protection_stop_hit=p.stop_hit,
            _protection_profit_hit=p.profit_hit,_pending_protection_exit=p.pending,
            _dispatch_protection_exit=p.dispatch,_pending_protection_stage=p.pending_stage,
            _dispatch_protection_stage=p.dispatch_stage,
            _exit_fresh_prices=lambda m:{k:v for k,v in self.market.items() if k in m},
            _exit_token_data=lambda m:None,_mark_hot_mint=lambda *a,**k:None,
            _chain_tradeable=lambda c:c=='solana',_volatility_trailing_pct=lambda h:.1,
            _liquidity_stop=lambda *a:(False,None),add_user_log=Mock(),
            _send_push_notification=Mock(),time=time,datetime=__import__('datetime'),
            TP_STAGE1_FRACTION_OF_TARGET=.5,TP_STAGE1_SELL_FRACTION=.5,
            TP_STAGE2_FRACTION_OF_TARGET=1,TP_STAGE2_SELL_FRACTION=.5,
            TP1_MULTIPLE=2,TP1_SELL_FRACTION=.5)
        functions(self.ns,'_pos_sl_frac','_pos_tp_frac','_exit_pass')
        def sell(uid,us,wallet,mint,pos,price,label,amount,spend,reason,*args,**kw):
            self.calls.append((mint,reason,price))
            self.release.wait(2)
            if self.fail:
                return False,0,0
            us['positions'][mint] = dict(amount=0,buy_price=0,spend=0)
            return True,price,amount
        self.ns['_bot_execute_exit'] = sell
        self.locks = {}
        self.ns['_get_sell_lock'] = lambda w,m,c:self.locks.setdefault(m,threading.Lock())
        self.ns['_upsert_open_position'] = lambda uid,w,m,pos,**kw:self.us['positions'].update({m:dict(pos)})
        def partial(*args):
            self.calls.append((args[3],args[9],args[5]))
            self.release.wait(2)
            return (not self.fail,args[5],args[7]) if not self.fail else (False,0,0)
        self.ns['_bot_execute_exit_locked'] = partial

    def tearDown(self):
        self.release.set()
        eventually(lambda: not any(k[0]==self.db for k in p._BUSY))
        self.tmp.cleanup()

    def position(self,mint='A',base='SOL',opened=1):
        pos=dict(amount=100,buy_price=.000001 if base=='SOL' else .0001,
            spend=.0001,base=base,chain='solana',symbol=mint,
            sl_pct=8,tp_pct=18,opened_at=opened)
        self.us['positions'][mint]=pos
        self.market[mint]=.0001
        return pos

    def runpass(self):
        self.ns['_exit_pass']()

    def test_usd_feed_is_not_compared_to_sol_entry(self):
        self.position()
        self.runpass()
        self.assertEqual(self.calls,[])
        self.assertAlmostEqual(p.market_price(self.us['positions']['A'],.0001,100),.000001)

    def test_legacy_usdc_basis_is_not_divided_by_sol(self):
        self.position(base='USDC')
        self.runpass()
        self.assertEqual(self.calls,[])

    def test_exact_stop_touch_triggers(self):
        self.position()
        self.market['A']=.0001*.92
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==1))
        self.assertTrue(self.calls[0][1].startswith('STOP LOSS'))

    def test_exact_profit_touch_triggers(self):
        self.position()
        self.market['A']=.0001*1.18
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==1))
        self.assertTrue(self.calls[0][1].startswith('TAKE PROFIT'))

    def test_inside_thresholds_does_not_trigger(self):
        self.position()
        for usd in [.0001*.921,.0001*1.179]:
            self.market['A']=usd
            self.runpass()
        self.assertEqual(self.calls,[])

    def test_missing_or_invalid_sol_and_token_prices_are_unknown(self):
        for bad in [0,None,float('nan'),float('inf')]:
            self.assertEqual(p.market_price({'base':'SOL'},.1,bad),0)
            self.assertEqual(p.market_price({'base':'USDC'},bad,100),0)
        self.position()
        self.ns['_sol_price_usd']=0
        self.runpass()
        self.assertEqual(self.calls,[])

    def test_failed_trigger_survives_rebound_and_process_restore(self):
        pos=self.position()
        self.fail=True
        self.market['A']=.00009
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==1 and not p._BUSY))
        self.assertGreater(self.us['positions']['A']['amount'],0)
        restored={k:v for k,v in pos.items() if not k.startswith('_')}
        self.us['positions']['A']=restored
        self.market['A']=.000105
        self.fail=False
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==2))
        self.assertTrue(self.calls[1][1].startswith('STOP LOSS'))

    def test_pending_exit_does_not_depend_on_a_second_price(self):
        pos=self.position()
        p.latch(self.db,1,'WalletCase','A',pos,'STOP LOSS -8%',.00000092)
        self.market.clear()
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==1))

    def test_slow_sale_does_not_delay_another_mint(self):
        self.release.clear()
        self.position('A');self.position('B')
        self.market.update(A=.00009,B=.00012)
        start=time.monotonic()
        self.runpass()
        self.assertLess(time.monotonic()-start,.2)
        self.assertTrue(eventually(lambda:len(self.calls)==2,.5))

    def test_many_checks_schedule_one_sale_for_a_position(self):
        self.release.clear()
        self.position()
        self.market['A']=.00009
        for _ in range(15):
            self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==1))
        self.release.set()
        self.assertTrue(eventually(lambda:not p._BUSY))
        self.runpass()
        self.assertEqual(len(self.calls),1)

    def test_old_intent_cannot_apply_to_a_new_position(self):
        old=self.position()
        p.latch(self.db,1,'WalletCase','A',old,'STOP LOSS -8%',.00000092)
        new=self.position(opened=2)
        self.assertIsNone(p.pending(self.db,1,'WalletCase','A',new))
        self.runpass()
        self.assertEqual(self.calls,[])

    def test_manual_unprotected_holdings_are_never_auto_sold(self):
        pos=self.position()
        pos.update(source='manual',protect=False)
        self.market['A']=.00001
        self.runpass()
        self.assertEqual(self.calls,[])

    def test_hard_stop_still_protects_trailing_runner(self):
        pos=self.position()
        pos.update(trailing_enabled=True,tp1_hit=True,tp2_hit=True,trail_peak=.0000011)
        self.market['A']=.00009
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==1))
        self.assertTrue(self.calls[0][1].startswith('STOP LOSS'))

    def test_liquidity_quote_uses_matching_units(self):
        pos=self.position()
        ns=dict(_exit_realizable_price=lambda m,a:(.0001,1),
            _protection_price=p.market_price,_sol_price_usd=100)
        functions(ns,'_liquidity_stop')
        hit,change=ns['_liquidity_stop'](pos,'A',.000001,.08)
        self.assertFalse(hit)
        self.assertAlmostEqual(change,0)
        self.assertEqual(pos['_sell_value_ratio'],1)

    def test_full_exit_closes_under_shared_manual_sell_lock(self):
        pos=self.position()
        lock=threading.Lock()
        closed=[]
        ns=dict(_chain_tradeable=lambda c:True,add_user_log=Mock(),
            _get_sell_lock=lambda *a:lock,
            _bot_execute_exit_locked=lambda *a:(True,.000001,100),
            _close_open_position=lambda *a,**k:closed.append(lock.locked()))
        functions(ns,'_bot_execute_exit')
        result=ns['_bot_execute_exit'](1,self.us,'WalletCase','A',pos,.000001,'A',100,.0001,
            'STOP LOSS -8%',False,'cipher',None,True)
        self.assertTrue(result[0]);self.assertEqual(closed,[True])
        self.assertFalse(lock.locked())

    def test_manual_lock_prevents_duplicate_auto_sell(self):
        pos=self.position()
        lock=threading.Lock();lock.acquire()
        callback=Mock()
        ns=dict(_chain_tradeable=lambda c:True,add_user_log=Mock(),
            _get_sell_lock=lambda *a:lock,_bot_execute_exit_locked=callback)
        functions(ns,'_bot_execute_exit')
        try:
            result=ns['_bot_execute_exit'](1,self.us,'WalletCase','A',pos,.000001,'A',100,.0001,
                'STOP LOSS',False,'cipher',None,True)
            self.assertFalse(result[0]);callback.assert_not_called()
        finally:lock.release()

    def test_stale_worker_cannot_sell_new_position_generation(self):
        old=self.position();self.position(opened=2)
        lock=threading.Lock();callback=Mock()
        ns=dict(_chain_tradeable=lambda c:True,add_user_log=Mock(),
            _get_sell_lock=lambda *a:lock,_bot_execute_exit_locked=callback)
        functions(ns,'_bot_execute_exit')
        result=ns['_bot_execute_exit'](1,self.us,'WalletCase','A',old,.000001,'A',100,.0001,
            'STOP LOSS',False,'cipher',None,True)
        self.assertFalse(result[0]);callback.assert_not_called()

    def test_confirmed_swap_remains_success_when_trade_log_fails(self):
        @contextlib.contextmanager
        def key(*a):yield 'test-key'
        ns=dict(_use_key=key,_sell_and_get_realized=lambda *a,**kw:(True,.000001,100),
            _record_user_trade=Mock(side_effect=sqlite3.OperationalError('test failure')))
        functions(ns,'_bot_execute_exit_locked')
        result=ns['_bot_execute_exit_locked'](1,self.us,'WalletCase','A',self.position(),
            .000001,'A',100,.0001,'STOP LOSS',False,'cipher','solana',True,{})
        self.assertTrue(result[0])


    def test_staged_sale_does_not_block_another_stop(self):
        self.release.clear()
        a=self.position('A');a['trailing_enabled']=True
        self.position('B')
        self.market.update(A=.00011,B=.00009)
        start=time.monotonic()
        self.runpass()
        self.assertLess(time.monotonic()-start,.2)
        self.assertTrue(eventually(lambda:len(self.calls)==2,.5))

    def test_confirmed_stage_updates_actual_remainder(self):
        pos=self.position()
        pos['trailing_enabled']=True
        self.market['A']=.00011
        self.runpass()
        self.assertTrue(eventually(lambda:not p._BUSY and self.us['positions']['A'].get('tp1_hit')))
        self.assertEqual(self.us['positions']['A']['amount'],50)
        self.assertAlmostEqual(self.us['positions']['A']['spend'],.00005)

    def test_completed_stage_is_not_repeated_after_restart(self):
        pos=self.position()
        pos['trailing_enabled']=True
        self.market['A']=.00011
        self.runpass()
        self.assertTrue(eventually(lambda:not p._BUSY and self.us['positions']['A'].get('tp1_hit')))
        self.us['positions']['A']={k:v for k,v in self.us['positions']['A'].items()
            if not k.startswith('_') and k not in ('tp1_hit','tp2_hit','trail_peak')}
        self.runpass()
        self.assertEqual(len(self.calls),1)
        self.assertTrue(self.us['positions']['A']['tp1_hit'])

    def test_failed_stage_is_restored_after_restart_and_rebound(self):
        pos=self.position()
        pos['trailing_enabled']=True
        self.fail=True
        self.market['A']=.00011
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==1 and not p._BUSY))
        self.us['positions']['A']={k:v for k,v in pos.items() if not k.startswith('_')}
        self.fail=False;self.market['A']=.000105
        self.runpass()
        self.assertTrue(eventually(lambda:len(self.calls)==2))
        self.assertTrue(self.calls[1][1].startswith('TAKE PROFIT 1'))


class FeedTests(unittest.TestCase):
    def ctx(self):
        return dict(_exit_price_lock=threading.Lock(),_exit_fetch_lock=threading.Lock(),
            _exit_watched={},_exit_price_cache={},_EXIT_WATCH_TTL=10,
            _EXIT_PRICE_TTL=1,_EXIT_PRICE_MAX_AGE=3)

    def test_price_read_never_waits_for_network_and_stale_nan_are_ignored(self):
        ctx=self.ctx();release=threading.Event()
        def fetch(mints):
            release.wait(2)
            return {'A':2}
        ctx['_exit_fetch_prices']=fetch
        ctx['_exit_price_cache']={'Old':(time.time()-4,2),'Bad':(time.time(),float('nan'))}
        start=time.monotonic()
        self.assertEqual(p.prices(ctx,{'A':'solana','Old':'solana','Bad':'solana'}),{})
        self.assertLess(time.monotonic()-start,.1)
        release.set()
        self.assertTrue(eventually(lambda:'A' in ctx['_exit_price_cache']))
        self.assertEqual(p.prices(ctx,{'A':'solana'}),{'A':2})

    def test_fast_source_publishes_without_waiting_for_slow_source(self):
        ctx=self.ctx();release=threading.Event()
        class Response:
            status_code=200
            def json(self):return {'A':{'usdPrice':2}}
        class Requests:
            def get(self,*a,**kw):
                release.wait(2);return Response()
        class Dex:
            status_code=200
            def json(self):return {'pairs':[{'chainId':'solana','baseToken':{'address':'A'},
                                             'priceUsd':'2','liquidity':{'usd':100}}]}
        ctx.update(os=os,requests=Requests(),_dex_get=lambda *a,**kw:Dex())
        ctx['_exit_fetch_prices']=lambda m:p.fetch_prices(ctx,m)
        p.prices(ctx,{'A':'solana'})
        self.assertTrue(eventually(lambda:'A' in ctx['_exit_price_cache'],.3))
        release.set()
        self.assertTrue(eventually(lambda:not ctx['_exit_fetch_lock'].locked()))


if __name__=='__main__':
    unittest.main()
