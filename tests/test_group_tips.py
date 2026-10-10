"""Signed group and DM tips, temporary SQLite and fake RPC; no real funds."""
import base64
import json
import sqlite3
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask, request
from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction
import group_tips as tips
import portfolio_token_withdraw as provider
import tip_experience as ledger


@pytest.fixture
def env(tmp_path):
    path = str(tmp_path/'test.db')
    keys = [None] + [Keypair() for _ in range(51)]
    with sqlite3.connect(path) as c:
        c.executescript('''CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,avatar_url TEXT,wallet_address TEXT,encrypted_private_key TEXT);
        CREATE TABLE group_chats(id INTEGER PRIMARY KEY,change_version INTEGER DEFAULT 0);
        INSERT INTO group_chats(id) VALUES(1);
        CREATE TABLE group_chat_members(chat_id INTEGER,user_id INTEGER,history_from_id INTEGER DEFAULT 0);
        CREATE TABLE group_chat_messages(id INTEGER PRIMARY KEY,chat_id INTEGER,sender_id INTEGER,kind TEXT,body TEXT,created_at TEXT,version INTEGER DEFAULT 0);
        CREATE TABLE direct_messages(id INTEGER PRIMARY KEY,sender_id INTEGER,receiver_id INTEGER,message TEXT,message_type TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE notifications(id INTEGER PRIMARY KEY,user_id INTEGER,type TEXT,content TEXT,link TEXT,actor_wallet TEXT);''')
        for i in range(1,51):
            c.execute('INSERT INTO users VALUES(?,?,?,?,?)',(i,'User'+str(i),'',str(keys[i].pubkey()),'key'))
        c.executemany('INSERT INTO group_chat_members(chat_id,user_id) VALUES(1,?)',[(i,) for i in range(1,8)])
    @contextmanager
    def use_key(_, wallet):
        yield str(next(k for k in keys[1:] if str(k.pubkey()) == wallet))
    d=SimpleNamespace(app=Flask(__name__),DB_FILE=path,SOL_NETWORK_RESERVE=.001,
        _authenticated_wallet=lambda: str(keys[int(request.headers.get('X-User','1'))].pubkey()),
        _get_uid=lambda c,w:c.execute('SELECT id FROM users WHERE wallet_address=?',(w,)).fetchone()[0],
        _get_trading_wallet_address=lambda w:w,_use_key=use_key,_sanitize=lambda x:x,
        _validate_csrf=lambda v:v=='valid',is_valid_solana_address=lambda w:bool(w),
        rate_limit=lambda *_:lambda f:f,
        _major_quote_snapshot=lambda:{'prices':{'SOL':{'price':100,'observed_at':time.time()}}})
    state={'sent':[], 'statuses':{}, 'height':1, 'simulations':0, 'reject':False, 'timeout':False}
    def rpc(_, method, params, **kw):
        result={'getLatestBlockhash':{'value':{'blockhash':str(Hash.default()),'lastValidBlockHeight':100}},
                'getBalance':{'value':100*10**9},'getFeeForMessage':{'value':5000},
                'getBlockHeight':state['height']}.get(method)
        if method=='simulateTransaction':
            state['simulations']+=1
            result={'value':{'err':'rejected' if state['reject'] else None}}
        if method=='getSignatureStatuses':
            result={'value':[state['statuses'].get(s) for s in params[0]]}
        if method=='sendTransaction':
            tx=Transaction.from_bytes(base64.b64decode(params[0]));tx.verify()
            assert len(bytes(tx)) <= 1232
            state['sent'].append(params[0]);result=str(tx.signatures[0])
            if state['timeout']:raise TimeoutError('fake response loss')
        return result,'fake'
    with patch.object(provider,'_rpc_call_any',side_effect=rpc),patch.object(provider,'_fee_payer_rent_lamports',return_value=890880):
        with patch.object(tips.threading.Thread, 'start'):
            tips.install(d)
        yield d,state,d.app.test_client()


def quote(client,path='/api/group-chats/1/tips',**data):
    return client.post(path+'/quote',headers={'X-CSRF-Token':'valid'},json={'amount_usdc':6,**data})


def confirm(client,t,path='/api/group-chats/1/tips'):
    return client.post(path+'/'+t['id']+'/confirm',headers={'X-CSRF-Token':'valid'},json={})


def rows(d,sql,args=()):
    with sqlite3.connect(d.DB_FILE) as c:return c.execute(sql,args).fetchall()


def test_equal_split_review_and_private_confirmation(env):
    d,s,c=env;t=quote(c).json['tip']
    assert t['recipient_count']==6 and t['per_person_sol']==.01 and t['total_sol']==.06
    assert t['total_debit_sol']==.060005 and not s['sent']
    assert 'address' not in json.dumps(t) and 'wallet' not in json.dumps(t)
    confirm(c,t);assert len(s['sent'])==1
    assert len(rows(d,'SELECT id FROM tip_transactions'))==6
    assert not rows(d,'SELECT id FROM notifications')
    # Retry the persisted review, including after re-install/restart.
    tips.install(d);confirm(c,t);assert len(s['sent'])==1
    private=c.get('/api/group-chats/1/tips/'+t['id'],headers={'X-User':'2'}).json['tip']
    assert private['per_person_usdc']==1 and 'recipients' not in private and 'total_sol' not in private
    sig=str(Transaction.from_bytes(base64.b64decode(s['sent'][0])).signatures[0])
    s['statuses'][sig]={'err':None,'confirmationStatus':'confirmed'}
    tips.reconcile(d,t['id'])
    assert len(rows(d,"SELECT id FROM tip_transactions WHERE status='confirmed'"))==6
    assert len(rows(d,'SELECT id FROM notifications'))==6
    assert json.loads(rows(d,'SELECT body FROM group_chat_messages')[0][0])['status']=='confirmed'
    tips.reconcile(d,t['id']);assert len(rows(d,'SELECT id FROM notifications'))==6

    # A sender may remove the chat card even while chain status is changing.
    # Reconciliation must NOT resurrect that card; the private ledger remains.
    with sqlite3.connect(d.DB_FILE) as db:
        db.execute("UPDATE group_chat_messages SET kind='deleted',body='__tip_removed_from_chat__' WHERE chat_id=1")
        db.execute("UPDATE group_tips SET state='submitted' WHERE id=?", (t['id'],))
    tips.reconcile(d, t['id'])
    assert rows(d, 'SELECT kind,body FROM group_chat_messages') == [
        ('deleted', '__tip_removed_from_chat__')]
    assert len(rows(d, "SELECT id FROM tip_transactions WHERE status='confirmed'")) == 6



def test_membership_changed_expiry_and_csrf(env):
    d,s,c=env;t=quote(c).json['tip']
    with sqlite3.connect(d.DB_FILE) as db:db.execute('DELETE FROM group_chat_members WHERE user_id=7')
    assert confirm(c,t).status_code==400 and not s['sent']
    assert c.post('/api/group-chats/1/tips/quote',json={'amount_usdc':6}).status_code==403
    assert c.get('/api/group-chats/1/tips/'+t['id'],headers={'X-User':'50'}).status_code==403
    t=quote(c).json['tip']
    with sqlite3.connect(d.DB_FILE) as db:
        q=json.loads(db.execute('SELECT quote FROM group_tips WHERE id=?',(t['id'],)).fetchone()[0]);q['expires']=0
        db.execute('UPDATE group_tips SET quote=? WHERE id=?',(json.dumps(q),t['id']))
    assert confirm(c,t).status_code==400 and not s['sent']


@pytest.mark.parametrize('amount',['NaN','Infinity',0,-2,10001,'bad'])
def test_invalid_amounts(env,amount):
    d,s,c=env;assert quote(c,amount_usdc=amount).status_code==400 and not s['sent']


def test_preflight_all_before_broadcast_and_large_groups(env):
    d,s,c=env
    with sqlite3.connect(d.DB_FILE) as db:
        db.executemany('INSERT INTO group_chat_members(chat_id,user_id) VALUES(1,?)',[(i,) for i in range(8,51)])
    t=quote(c,amount_usdc=49).json['tip'];assert t['recipient_count']==49
    s['reject']=True
    assert confirm(c,t).status_code==400 and not s['sent']
    s['reject']=False;confirm(c,t);assert len(s['sent'])==4
    assert len(rows(d,'SELECT id FROM tip_transactions'))==49
    for i,encoded in enumerate(s['sent']):
        signature=str(Transaction.from_bytes(base64.b64decode(encoded)).signatures[0])
        s['statuses'][signature]={'err':None if i==0 else 'failed','confirmationStatus':'confirmed'}
    tips.reconcile(d,t['id'])
    receipt=c.get('/api/group-chats/1/tips/'+t['id']).json['tip']
    assert receipt['status']=='partial' and receipt['confirmed_recipients']==16


def test_ambiguous_network_only_rebroadcasts_same_bytes(env):
    d,s,c=env;t=quote(c).json['tip'];s['timeout']=True
    assert confirm(c,t).json['tip']['status']=='submitted'
    with sqlite3.connect(d.DB_FILE) as db:db.execute('UPDATE group_tips SET attempt=0 WHERE id=?',(t['id'],))
    tips.reconcile(d,t['id']);assert len(s['sent'])==2 and s['sent'][0]==s['sent'][1]
    s['height']=101;tips.reconcile(d,t['id']);assert len(s['sent'])==2


def test_direct_tip_one_person_and_pair_only(env):
    d,s,c=env;path='/api/messages/2/tips';t=quote(c,path).json['tip']
    assert t['recipient_count']==1 and t['per_person_usdc']==6
    assert confirm(c,t,path).json['ok'] and len(s['sent'])==1
    assert len(rows(d,'SELECT id FROM direct_messages'))==1
    assert not rows(d,'SELECT id FROM group_chat_messages')
    assert c.get('/api/messages/1/tips/'+t['id'],headers={'X-User':'2'}).json['tip']['recipient']
    assert c.get('/api/messages/2/tips/'+t['id'],headers={'X-User':'3'}).status_code==403
    assert quote(c,'/api/messages/1/tips').status_code==403


def test_same_amount_separate_reviews_have_distinct_signatures(env):
    d,s,c=env
    a=quote(c).json['tip'];b=quote(c).json['tip'];confirm(c,a);confirm(c,b)
    assert len(s['sent'])==2 and s['sent'][0]!=s['sent'][1]


def test_broadcast_does_not_wait_for_status_provider(env):
    d,s,c=env;t=quote(c).json['tip']
    old=provider._rpc_call_any.side_effect
    def unavailable(d,method,params,**kw):
        if method=='getSignatureStatuses':raise TimeoutError('status RPC unavailable')
        return old(d,method,params,**kw)
    with patch.object(provider,'_rpc_call_any',side_effect=unavailable):
        assert confirm(c,t).json['tip']['status']=='submitted'
    assert len(s['sent'])==1


def test_confirm_refreshes_blockhash_before_signing(env):
    d,s,c=env;t=quote(c).json['tip'];fresh=Hash.new_unique()
    old=provider._rpc_call_any.side_effect
    def renewed(d,method,params,**kw):
        if method=='getLatestBlockhash':
            return {'value':{'blockhash':str(fresh),'lastValidBlockHeight':250}},'fresh-provider'
        if method=='simulateTransaction':assert kw.get('preferred_url')=='fresh-provider'
        return old(d,method,params,**kw)
    with patch.object(provider,'_rpc_call_any',side_effect=renewed):confirm(c,t)
    tx=Transaction.from_bytes(base64.b64decode(s['sent'][0]))
    assert tx.message.recent_blockhash==fresh
    q=json.loads(rows(d,'SELECT quote FROM group_tips WHERE id=?',(t['id'],))[0][0])
    assert q['last_height']==250
    confirm(c,t);assert len(s['sent'])==1


def test_archived_transaction_prevents_false_expiry(env):
    d,s,c=env;t=quote(c).json['tip'];confirm(c,t);s['height']=101
    old=provider._rpc_call_any.side_effect
    def archived(d,method,params,**kw):
        if method=='getTransaction':return {'meta':{'err':None}},'archive'
        return old(d,method,params,**kw)
    with patch.object(provider,'_rpc_call_any',side_effect=archived):tips.reconcile(d,t['id'])
    assert c.get('/api/group-chats/1/tips/'+t['id']).json['tip']['status']=='confirmed'
    assert len(s['sent'])==1


def test_send_failure_has_safe_diagnosis(env):
    d,s,c=env;t=quote(c).json['tip'];s['timeout']=True
    receipt=confirm(c,t).json['tip']
    assert 'Network response delayed' in receipt['status_detail']
    assert 'fake response loss' not in str(receipt)


def test_quote_rpc_is_bounded_and_does_not_broadcast(env):
    d, state, client = env
    calls = []
    original = provider._rpc_call_any.side_effect

    def rpc(d, method, params, **kw):
        calls.append((method, kw))
        return original(d, method, params, **kw)

    with patch.object(provider, '_rpc_call_any', side_effect=rpc):
        response = quote(client, amount_usdc=1)

    assert response.status_code == 200
    assert response.json['tip']['recipient_count'] == 6
    for method in ('getLatestBlockhash', 'getFeeForMessage', 'getBalance'):
        options = next(kw for name, kw in calls if name == method)
        assert options['timeout'] == 4
        assert options['skip_demo'] is True
        assert options['preferred_url'] is not None
        assert options['max_providers'] == 3
    assert not any(method == 'getMinimumBalanceForRentExemption' for method, _ in calls)
    assert state['sent'] == []


def test_group_quote_and_confirmation_prefer_operational_rpc(env):
    d, state, client = env
    calls = []
    original = provider._rpc_call_any.side_effect

    def rpc(d, method, params, **kw):
        calls.append((method, dict(kw)))
        return original(d, method, params, **kw)

    with patch.object(provider, '_rpc_call_any', side_effect=rpc):
        tip = quote(client, amount_usdc=1).json['tip']
        confirmed = confirm(client, tip)

    assert confirmed.status_code == 200
    assert len(state['sent']) == 1
    quote_call = next(kw for method, kw in calls if method == 'getLatestBlockhash')
    assert quote_call['preferred_url'] == 'https://solana-rpc.publicnode.com'
    assert quote_call['skip_demo'] is True
    assert any(method == 'simulateTransaction' and kw['skip_demo'] is True
               for method, kw in calls)
    assert any(method == 'sendTransaction' and kw['skip_demo'] is True
               for method, kw in calls)


def test_chat_tips_filter_broken_demo_rpc_but_retain_live_fallback():
    d = SimpleNamespace(
        CLAIM_SOL_RPCS=['https://solana-mainnet.g.alchemy.com/v2/demo',
                        'https://mainnet.helius-rpc.com/?api-key=demo',
                        'https://api.mainnet-beta.solana.com'])
    calls = []

    def rpc(url, method, params, timeout=15):
        calls.append(url)
        if 'publicnode.com' in url:
            raise TimeoutError('test provider timed out')
        return {'value': {'blockhash': 'test'}}

    with patch.object(provider, '_rpc_call', side_effect=rpc):
        result, url = provider._rpc_call_any(
            d, 'getLatestBlockhash', [], preferred_url='https://solana-rpc.publicnode.com',
            timeout=4, max_providers=3, skip_demo=True)
    assert result['value']['blockhash'] == 'test'
    assert url == 'https://api.mainnet-beta.solana.com'
    assert calls == ['https://solana-rpc.publicnode.com',
                     'https://api.mainnet-beta.solana.com']


def test_quote_rpc_failure_returns_recoverable_error_without_sending(env):
    d, state, client = env
    original = provider._rpc_call_any.side_effect

    def rpc(d, method, params, **kw):
        if method == 'getFeeForMessage':
            raise TimeoutError('private RPC error details')
        return original(d, method, params, **kw)

    with patch.object(provider, '_rpc_call_any', side_effect=rpc):
        response = quote(client)

    assert response.status_code == 400
    assert response.json['ok'] is False
    assert 'Solana did not respond in time' in response.json['msg']
    assert 'private RPC error details' not in response.get_data(as_text=True)
    assert rows(d, 'SELECT id FROM group_tips') == []
    assert state['sent'] == []


def test_sender_excluded_even_when_another_member_uses_sender_trading_wallet(env):
    d, state, client = env
    with sqlite3.connect(d.DB_FILE) as db:
        owner = db.execute('SELECT wallet_address FROM users WHERE id=1').fetchone()[0]
        linked = db.execute('SELECT wallet_address FROM users WHERE id=2').fetchone()[0]
    d._get_trading_wallet_address = lambda wallet: owner if wallet == linked else wallet

    response = quote(client, amount_usdc=6)
    assert response.status_code == 200
    tip = response.json['tip']
    assert tip['recipient_count'] == 5
    assert {r['user_id'] for r in tip['recipients']} == {3, 4, 5, 6, 7}
    assert tip['per_person_usdc'] == pytest.approx(1.2)
    assert not state['sent']

    receipt = confirm(client, tip)
    assert receipt.status_code == 200
    assert len(state['sent']) == 1
    assert {r[0] for r in rows(d, 'SELECT recipient_user_id FROM tip_transactions')} == {3, 4, 5, 6, 7}


@pytest.mark.parametrize('tampering', ['sender_id', 'sender_wallet'])
def test_confirm_rejects_a_quote_containing_sender(env, tampering):
    d, state, client = env
    tip = quote(client).json['tip']
    with sqlite3.connect(d.DB_FILE) as db:
        q = json.loads(db.execute('SELECT quote FROM group_tips WHERE id=?',
                                  (tip['id'],)).fetchone()[0])
        if tampering == 'sender_id':
            q['recipients'][0]['user_id'] = 1
        else:
            q['recipients'][0]['address'] = db.execute(
                'SELECT wallet_address FROM users WHERE id=1').fetchone()[0]
        db.execute('UPDATE group_tips SET quote=? WHERE id=?',
                   (json.dumps(q), tip['id']))
    response = confirm(client, tip)
    assert response.status_code == 400
    assert 'cannot include your own account' in response.json['msg']
    assert not state['sent']
    assert rows(d, 'SELECT state,plan FROM group_tips WHERE id=?', (tip['id'],)) == [('quoted', None)]


def test_sender_wallet_alias_added_after_quote_is_rejected_at_confirm(env):
    d, state, client = env
    tip = quote(client).json['tip']
    with sqlite3.connect(d.DB_FILE) as db:
        owner = db.execute('SELECT wallet_address FROM users WHERE id=1').fetchone()[0]
        linked = db.execute('SELECT wallet_address FROM users WHERE id=2').fetchone()[0]
    d._get_trading_wallet_address = lambda wallet: owner if wallet == linked else wallet
    response = confirm(client, tip)
    assert response.status_code == 400
    assert not state['sent']


def test_no_group_tip_if_every_other_member_uses_sender_wallet(env):
    d, state, client = env
    with sqlite3.connect(d.DB_FILE) as db:
        owner = db.execute('SELECT wallet_address FROM users WHERE id=1').fetchone()[0]
    d._get_trading_wallet_address = lambda wallet: owner
    response = quote(client)
    assert response.status_code == 400
    assert 'no other eligible members' in response.json['msg']
    assert not state['sent']



def test_recipient_audit_write_never_runs_under_tip_write_lock(env):
    d, state, client = env
    blocked = []
    def derive(wallet):
        try:
            with sqlite3.connect(d.DB_FILE, timeout=.05) as c:
                c.execute('UPDATE users SET username=username WHERE wallet_address=?', (wallet,))
        except sqlite3.OperationalError:
            blocked.append(wallet)
            raise
        return wallet
    d._get_trading_wallet_address = derive
    t = quote(client).json['tip']
    response = confirm(client, t)
    assert response.status_code == 200 and response.json['ok']
    assert not blocked, 'wallet auditing attempted while the group tip held a write lock'
    assert len(state['sent']) == 1
    assert confirm(client, t).json['ok']
    assert len(state['sent']) == 1


def test_changed_receiving_key_before_commit_prevents_broadcast(env):
    d, state, client = env
    t = quote(client).json['tip']
    original = provider._rpc_call_any.side_effect
    def rpc(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[1] == 'simulateTransaction':
            with sqlite3.connect(d.DB_FILE) as c:
                c.execute("UPDATE users SET encrypted_private_key='changed' WHERE id=2")
        return result
    with patch.object(provider, '_rpc_call_any', side_effect=rpc):
        response = confirm(client, t)
    assert not response.json['ok']
    assert not state['sent']
    assert rows(d, "SELECT state FROM group_tips WHERE id=?", (t['id'],))[0][0] == 'quoted'
