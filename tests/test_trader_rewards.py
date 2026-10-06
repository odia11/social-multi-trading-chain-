import datetime as dt
import sqlite3
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, redirect, request, render_template, make_response
import trader_rewards as r

NOW=1780000000.0

@pytest.fixture
def db(tmp_path):
    path=str(tmp_path/'rewards.sqlite')
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,created_at TEXT,is_verified INTEGER)')
        old=dt.datetime.fromtimestamp(NOW-20*86400,dt.timezone.utc).isoformat()
        c.executemany('INSERT INTO users VALUES(?,?,?,?)',[(1,'alice',old,0),(2,'bob',old,1)])
    r.initialize(path)
    return path


def sig(i):return str(i%9+1)*86+str((i//9)%9+1)


def trade(db,i,day=0,amount=50,side='buy',mint=None):
    return r.record_confirmed_trade(db,'alice',sig(i),mint or 'mint'+str(i),side,amount,'USDC',0,NOW-day*86400)


def test_thresholds_and_expiry(db):
    for i in range(5):assert trade(db,i,day=i%3)
    result=r.progress(db,'alice',NOW)
    assert (result['status'],result['volume_usdc'],result['trades'],result['trading_days'])==('Active Trader',250,5,3)
    for i in range(5,10):assert trade(db,i,day=i-3,amount=450)
    assert r.progress(db,'alice',NOW)['status']=='Pro Trader'
    assert r.progress(db,'alice',NOW+31*86400)['status']=='New Member'
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT is_verified FROM users WHERE id=1').fetchone()[0]==0
        c.execute('UPDATE users SET created_at=? WHERE id=1',(dt.datetime.fromtimestamp(NOW-13*86400,dt.timezone.utc).isoformat(),))
    assert r.progress(db,'alice',NOW)['status']=='New Member'


def test_no_fake_duplicate_or_repriced_volume(db):
    assert r.record_confirmed_trade(db,'alice',sig(1),'mint','buy',2,'SOL',125,NOW)
    assert not r.record_confirmed_trade(db,'bob',sig(1),'mint','buy',1000,'USDC',0,NOW)
    assert r.progress(db,'alice',NOW+86400)['volume_usdc']==250
    assert r.progress(db,'bob',NOW)['volume_usdc']==0
    for amount in (float('nan'),float('inf'),-5,0,.5):assert not trade(db,2,amount=amount)
    assert not r.record_confirmed_trade(db,'alice','invalid','mint','buy',999,'USDC',0,NOW)
    assert not r.record_confirmed_trade(db,'alice',sig(4),'mint','tip',999,'USDC',0,NOW)
    assert not r.record_confirmed_trade(db,'alice',sig(4),'mint','buy',2,'SOL',0,NOW)


def test_cooldown_and_review(db):
    assert trade(db,0,mint='one')
    assert trade(db,1,mint='one')
    result=r.progress(db,'alice',NOW)
    assert result['trades']==1
    assert trade(db,2,mint='one',side='sell')
    assert r.progress(db,'alice',NOW)['review_trades']==3
    assert r.progress(db,'alice',NOW)['trades']==0


def setup_app(db):
    app=Flask(__name__,template_folder='../templates')
    viewer=['alice'];role=['user']
    def no_cache(template,**kwargs):
        response=make_response(render_template(template,**kwargs))
        response.headers['Cache-Control']='private, no-store'
        return response
    app.jinja_env.globals['navbar_html']=lambda _:''
    d=SimpleNamespace(app=app,DB_FILE=db,request=request,jsonify=jsonify,redirect=redirect,
        _authenticated_wallet=lambda:viewer[0],_get_csrf_token=lambda:'test',
        _render_no_cache=no_cache,_require_role=lambda *roles:None if role[0] in roles else (jsonify(ok=False),403),
        _log_security_event=lambda *args:None)
    r.install(d)
    return app,viewer,role


def test_api_owner_only_and_no_client_write(db):
    trade(db,0)
    app,viewer,role=setup_app(db)
    with app.test_client() as client:
        viewer[0]=None
        assert client.get('/api/rewards/progress').status_code==401
        assert client.post('/api/rewards/progress',json={'volume':10000}).status_code==405
        viewer[0]='bob'
        response=client.get('/api/rewards/progress?wallet=alice')
        assert response.json['reward']['volume_usdc']==0
        assert response.headers['Cache-Control']=='private, no-store'
        with app.test_request_context('/'):
            helper=app.template_context_processors[None][-1]()['reward_status']
            assert set(helper('alice',details=True))=={'status'}
        viewer[0]='alice'
        retired=client.get('/rewards');assert retired.status_code==302 and retired.location.endswith('/')
        assert client.get('/api/rewards/progress').json['reward']['volume_usdc']==0 # fixture history now expired


def test_activity_unique_and_not_api_polling(db):
    app,viewer,role=setup_app(db)
    with app.test_client() as client:
        client.get('/api/rewards/progress');client.get('/api/rewards/progress')
        with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM reward_activity').fetchone()[0]==0
        client.get('/rewards');client.get('/rewards')
        with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM reward_activity').fetchone()[0]==0
        client.get('/');client.get('/')
        with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM reward_activity').fetchone()[0]==1
        viewer[0]=None;client.get('/rewards')
        with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM reward_activity').fetchone()[0]==1


def test_member_and_private_progress(db):
    with sqlite3.connect(db) as c:
        for i in range(7):c.execute('INSERT INTO reward_activity VALUES(1,?)',(dt.datetime.fromtimestamp(NOW-i*86400,dt.timezone.utc).date().isoformat(),))
    assert r.progress(db,'alice',NOW)['status']=='Active Member'
    assert r.progress(db,'alice',NOW+31*86400)['status']=='New Member'


def test_admin_review_authorized_only(db):
    trade(db,0,mint='one');trade(db,1,mint='one',side='sell')
    app,viewer,role=setup_app(db)
    with app.test_client() as client:
        data={'signature':sig(1),'decision':'eligible'}
        assert client.post('/api/admin/rewards/review',json=data).status_code==403
        role[0]='admin'
        assert client.post('/api/admin/rewards/review',json=data).status_code==200
        assert client.post('/api/admin/rewards/review',json=data).status_code==404
        assert client.post('/api/admin/rewards/review',json={'signature':sig(0),'decision':'magic'}).status_code==400
    assert r.progress(db,'alice',NOW)['trades']==1


def test_execution_hook_records_only_successful_real_fills(db):
    import ast
    import os
    import re
    import sys
    import subprocess
    from pathlib import Path
    from unittest.mock import patch
    source=Path('dashboard.py').read_text()
    tree=ast.parse(source)
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('_execute_user_swap_ex','_parse_swap_realized_amounts','_validated_execution_fee_rate')]
    captured={}
    namespace=dict(os=os,sys=sys,re=re,subprocess=subprocess,BASE='.',DB_FILE=db,FEE_RATE_TXN=.0075,
        _sol_price_usd=100,get_user_state=lambda wallet:{'positions':{}},
        _ensure_solana_gas=lambda *args,**kwargs:(True,''),_sol_fee_recipient=lambda:'recipient',
        _ext_hit=lambda *args:None,add_user_log=lambda *args:None,_redact_keys=lambda text:text)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'dashboard.py','exec'),namespace)
    output=f'BUY mint 0.52 SOL got:20 sol:0.52 fee_base:0.50 TX:{sig(1)}'
    with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
        assert namespace['_execute_user_swap_ex']('alice','fake','buy','mint','0.52')[0]
    with sqlite3.connect(db) as c:
        assert c.execute('SELECT volume_usdc FROM reward_trades').fetchone()[0]==50
    with patch('subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=output,stderr='')):
        assert not namespace['_execute_user_swap_ex']('alice','fake','buy','mint','0.52')[0]
    with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='no fill',stderr='')):
        assert not namespace['_execute_user_swap_ex']('alice','fake','buy','mint','0.52')[0]
    with patch('trader_rewards.record_confirmed_trade',side_effect=sqlite3.OperationalError('locked')):
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            assert namespace['_execute_user_swap_ex']('alice','fake','buy','mint','0.52')[0]
    with sqlite3.connect(db) as c:assert c.execute('SELECT COUNT(*) FROM reward_trades').fetchone()[0]==1


def test_rounding_cannot_unlock_badge_early(db):
    for i in range(5):trade(db,i,day=i%3,amount=49.9999)
    assert r.progress(db,'alice',NOW)['volume_usdc']==249.99
    assert r.progress(db,'alice',NOW)['status']=='New Member'


def test_review_page_is_role_scoped_and_escapes_profile_text(db):
    with sqlite3.connect(db) as c:
        c.execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''")
        c.execute('UPDATE users SET username=? WHERE id=1',('<img src=x onerror=alert(1)>',))
    trade(db,0,mint='one');trade(db,1,mint='one',side='sell')
    app,viewer,role=setup_app(db)
    with app.test_client() as client:
        assert client.get('/admin/rewards').status_code==403
        role[0]='analyst'
        assert client.get('/admin/rewards').status_code==403
        role[0]='admin'
        response=client.get('/admin/rewards')
        assert response.status_code==200
        assert b'&lt;img src=x' in response.data
        assert b'<img src=x' not in response.data
        assert b'data-decision="eligible"' in response.data
