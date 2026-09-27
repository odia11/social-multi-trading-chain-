"""Offline bridge status-loop restart regression, isolated SQLite and stubs."""
import ast
import datetime
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
SOURCE=(Path(__file__).resolve().parents[1]/'dashboard.py').read_text()
TREE=ast.parse(SOURCE)

def extract(name, context):
    node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),'dashboard.py','exec'),context)
    return context[name]

def run_once(state):
    with tempfile.TemporaryDirectory() as folder:
        db=str(Path(folder)/'offline.sqlite')
        with sqlite3.connect(db) as c:
            c.execute('''CREATE TABLE bridge_transactions (
                id INTEGER PRIMARY KEY, provider TEXT NOT NULL DEFAULT '0x', user_id INTEGER, wallet TEXT,
                source_tx_hash TEXT,source_chain TEXT,quote_id TEXT,
                poll_attempts INTEGER,polling_started_at TEXT,dest_chain TEXT,
                auto_buy_token_address TEXT,auto_buy_requested_usdc REAL,
                auto_buy_status TEXT,auto_buy_result TEXT,status TEXT,
                dest_tx_hash TEXT,actual_amount_out REAL,error_msg TEXT,
                recovery_info TEXT,updated_at TEXT)''')
            c.execute('CREATE TABLE notifications (user_id INTEGER,type TEXT,content TEXT,link TEXT,actor_wallet TEXT)')
            c.execute('''INSERT INTO bridge_transactions
                (user_id,wallet,source_tx_hash,source_chain,quote_id,
                 poll_attempts,dest_chain,auto_buy_token_address,
                 auto_buy_requested_usdc,auto_buy_status,status)
                 VALUES (7,'owner','0xtest','solana','quote',0,
                 'base','0xtoken',1.5,?,'bridge_filled')''',(state,))
        fired=[]
        polls=[]
        def execute(bridge_id,user_id,wallet,chain,token,amount):
            fired.append((bridge_id,chain,token,amount))
            with sqlite3.connect(db) as c:
                assert c.execute('SELECT auto_buy_status FROM bridge_transactions').fetchone()==('processing',)
                c.execute('UPDATE bridge_transactions SET auto_buy_status=?,auto_buy_result=? WHERE id=?',
                          ('done',json.dumps({'symbol':'MOCK','amount_usdc':1.0}),bridge_id))
        def status(chain,tx):
            polls.append((chain,tx))
            return dict(ok=True,status='bridge_filled',dest_tx_hash='0xsettled',
                        actual_amount_out=1.4,error_reason=None,recovery_info=None)
        def break_loop(seconds):raise StopIteration
        ns=dict(sqlite3=sqlite3,DB_FILE=db,json=json,datetime=datetime,
                time=SimpleNamespace(sleep=break_loop),
                _BRIDGE_MAX_POLL_SECONDS=1800,_BRIDGE_STATUS_INTERVAL=15,
                _BRIDGE_TERMINAL_STATUSES=frozenset({'bridge_filled','bridge_failed','origin_tx_reverted','timed_out'}),
                _BRIDGE_STATUS_NOTIFICATIONS={'bridge_filled':'Funding arrived'},
                _get_0x_bridge_status=status,_execute_auto_buy_after_bridge=execute,
                _send_push_notification=lambda *args:None)
        try:extract('_bridge_status_loop',ns)()
        except StopIteration:pass
        with sqlite3.connect(db) as c:
            row=c.execute('SELECT auto_buy_status,status FROM bridge_transactions').fetchone()
        return fired,polls,row

def test_filled_pending_recovers_without_replaying_claimed():
    fired,polls,row=run_once('pending')
    assert len(fired)==1 and len(polls)==1 and row==('done','bridge_filled'),(fired,polls,row)
    print('PASS filled pending bridge resumes exactly once using the stubbed buy')
    for state in ('processing','done','failed'):
        fired,polls,row=run_once(state)
        assert not fired and not polls and row[0]==state,(state,fired,polls,row)
    print('PASS processing/done/failed attached orders never replay after restart')

if __name__=='__main__':
    test_filled_pending_recovers_without_replaying_claimed()
