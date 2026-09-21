"""Tip UX contract tests. Temporary SQLite DB; mocked chain, no real transfers."""
import os
import sqlite3
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
import tip_experience as te


def fake_app():
    temp = tempfile.TemporaryDirectory()
    file = os.path.join(temp.name, 'test.sqlite')
    c = sqlite3.connect(file)
    c.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, username TEXT, wallet_address TEXT);
        INSERT INTO users VALUES(1,'Paddy','wallet-1');
        INSERT INTO users VALUES(2,'Forbi','wallet-2');
        INSERT INTO users VALUES(3,'Other','wallet-3');
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, type TEXT, content TEXT,
            link TEXT, actor_wallet TEXT, is_read INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    c.commit();c.close()
    app=Flask(__name__)
    d=SimpleNamespace(
        app=app, DB_FILE=file, EVM_CHAINS={},
        _authenticated_wallet=lambda: ({
            '1':'wallet-1','2':'wallet-2','3':'wallet-3'
        }.get(__import__('flask').request.headers.get('X-User'))),
        _send_push_notification=lambda *_:None)
    return temp,d


def query(d, sql, args=()):
    with te._db(d) as c:
        return c.execute(sql,args).fetchall()


def setup():
    temp,d=fake_app()
    with patch.object(te.threading.Thread,'start'):
        te.install(d)
    return temp,d


def test_submitted_is_not_confirmed_and_no_early_notification():
    temp,d=setup()
    try:
        tip=te.record_submitted(d,'wallet-1',1,2,'wallet-2',
                                '0.05','solana','sig-1')
        assert query(d,'SELECT status,confirmed_at FROM tip_transactions WHERE id=?',(tip,))[0]['status']=='submitted'
        assert not query(d,'SELECT * FROM notifications')
        with patch.object(te,'_chain_confirmation',return_value=(None,None)):
            res=d.app.test_client().get('/api/tips/mine',headers={'X-User':'1'}).json
            assert res['tips'][0]['status']=='submitted'
            assert res['tips'][0]['direction']=='sent'
        assert te.record_submitted(d,'wallet-1',1,2,'wallet-2','0.05','solana','sig-1')==tip
        assert len(query(d,'SELECT id FROM tip_transactions'))==1
    finally:temp.cleanup()


def test_confirmed_notifies_once_and_updates_totals_for_both_users():
    temp,d=setup()
    try:
        first=te.record_submitted(d,'wallet-1',1,2,'wallet-2',
                                  '0.05','solana','sig-2')
        second=te.record_submitted(d,'wallet-1',1,2,'wallet-2',
                                   '0.05','solana','sig-3')
        assert te._transition(d,first,'confirmed')
        assert not te._transition(d,first,'confirmed')
        assert te._transition(d,second,'confirmed')
        events=query(d,'SELECT * FROM notifications')
        assert len(events)==2
        assert events[0]['link']==f'/wallet?tab=history&tip={first}'
        client=d.app.test_client()
        stats=client.get('/api/profile/2/tip-stats').json
        assert stats['received_usdc']==0.10 and stats['supporters']==1
        assert stats['received_count']==2 and 'sent_usdc' not in stats
        own=client.get('/api/profile/1/tip-stats',headers={'X-User':'1'}).json
        assert own['sent_usdc']==0.10
        received=client.get('/api/tips/mine?role=received',headers={'X-User':'2'}).json
        assert len(received['tips'])==2
        assert all(x['direction']=='received' and x['status']=='confirmed' for x in received['tips'])
        assert all(x['confirmed_at'] for x in received['tips'])
    finally:temp.cleanup()



def test_tip_note_is_persisted_and_delivered_on_confirmation():
    temp,d=setup()
    try:
        tip=te.record_submitted(d,'wallet-1',1,2,'wallet-2','0.05',
                                'solana','sig-with-note',note='Keep going!\n')
        assert not query(d,'SELECT * FROM notifications')
        assert query(d,'SELECT note FROM tip_transactions')[0]['note']=='Keep going!'
        assert te._transition(d,tip,'confirmed')
        notice=query(d,'SELECT content FROM notifications')[0]['content']
        assert 'Keep going!' in notice
        detail=d.app.test_client().get(f'/api/tips/{tip}',
             headers={'X-User':'2'}).json['tip']
        assert detail['message']=='Keep going!'
    finally:temp.cleanup()



def test_failed_never_counts_or_notifies():
    temp,d=setup()
    try:
        tip=te.record_submitted(d,'wallet-1',1,2,'wallet-2',
                                '0.05','solana','sig-fail')
        assert te._transition(d,tip,'failed','on-chain error')
        assert not query(d,'SELECT * FROM notifications')
        assert d.app.test_client().get('/api/profile/2/tip-stats').json['received_usdc']==0
        detail=d.app.test_client().get(f'/api/tips/{tip}',headers={'X-User':'1'}).json['tip']
        assert detail['status']=='failed' and detail['failure_reason']=='on-chain error'
    finally:temp.cleanup()


def test_only_sender_and_recipient_can_get_tip_details():
    temp,d=setup()
    try:
        tip=te.record_submitted(d,'wallet-1',1,2,'wallet-2',
                                '0.05','solana','sig-private')
        client=d.app.test_client()
        assert client.get(f'/api/tips/{tip}').status_code==401
        assert client.get(f'/api/tips/{tip}',headers={'X-User':'3'}).status_code==404
        assert client.get('/api/tips/mine',headers={'X-User':'3'}).json['tips']==[]
        assert client.get(f'/api/tips/{tip}',headers={'X-User':'2'}).json['tip']['direction']=='received'
    finally:temp.cleanup()


def test_old_confirmed_rows_are_reverified_and_notification_enriched():
    temp,d=fake_app()
    try:
        c=sqlite3.connect(d.DB_FILE)
        c.executescript("""CREATE TABLE tip_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_user_id INTEGER, recipient_user_id INTEGER,
            sender_wallet TEXT, recipient_wallet TEXT, amount REAL,
            chain TEXT, tx_hash TEXT,
            status TEXT DEFAULT 'confirmed', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO tip_transactions
            (sender_user_id,recipient_user_id,sender_wallet,recipient_wallet,
             amount,chain,tx_hash,status)
            VALUES(1,2,'wallet-1','wallet-2',0.05,'solana','legacy','confirmed');
            INSERT INTO notifications(user_id,type,content,link,actor_wallet)
            VALUES(2,'tip','You received 0.05 USDC tip.','/wallet','wallet-1');
        """)
        c.commit();c.close()
        with patch.object(te.threading.Thread,'start'):
            te.install(d)
        assert query(d,'SELECT status FROM tip_transactions')[0]['status']=='submitted'
        assert d.app.test_client().get('/api/profile/2/tip-stats').json['received_usdc']==0
        assert te._transition(d,1,'confirmed')
        assert len(query(d,'SELECT * FROM notifications'))==1
        assert query(d,'SELECT link FROM notifications')[0]['link']=='/wallet?tab=history&tip=1'
    finally:temp.cleanup()


def test_chain_status_unknown_never_becomes_failed():
    d=SimpleNamespace(EVM_CHAINS={})
    with patch('portfolio_token_withdraw._rpc_call_any',
               return_value=({'value':[None]},'provider')):
        assert te._chain_confirmation(d,'solana','sig')==(None,None)
    with patch('portfolio_token_withdraw._rpc_call_any',
               return_value=({'value':[{'err':None,'confirmationStatus':'processed'}]},'provider')):
        assert te._chain_confirmation(d,'solana','sig')==(None,None)
    with patch('portfolio_token_withdraw._rpc_call_any',
               return_value=({'value':[{'err':None,'confirmationStatus':'finalized'}]},'provider')):
        assert te._chain_confirmation(d,'solana','sig')==('confirmed',None)


if __name__=='__main__':
    for n in sorted(x for x in globals() if x.startswith('test_')):
        globals()[n]()
        print('PASS',n)
    print('ALL TIP EXPERIENCE REGRESSIONS PASSED')
