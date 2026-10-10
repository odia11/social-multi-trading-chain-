"""Exercise real shared price helper and batch response without the monolith."""
import ast,json,threading,time,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from flask import Flask,request,jsonify
source=(Path(__file__).resolve().parents[1]/'dashboard.py').read_text()
tree=ast.parse(source)
ns=dict(time=time,threading=threading,json=json,ThreadPoolExecutor=ThreadPoolExecutor,
        request=request,jsonify=jsonify,EVM_CHAINS={},_LIVE_PRICE_TTL=1,_LIVE_PRICE_STALE_OK=20,
        _live_price_lock=threading.Lock(),_live_price_fetch_locks={},_live_price_cache={})
for name in ('_market_prices_for_pairs','api_market_prices_batch'):
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<market>','exec'),ns)
ns['_live_price_take']=lambda:True
ns['_market_prices_fetch']=lambda *a:None
ns['_live_price_cache'][('solana','pair')]=(time.time()-3,110)
assert ns['_market_prices_for_pairs']('solana',['pair'])=={'pair':110},'retain last price on upstream failure'
class Busy:
    def acquire(self,timeout):return False
    def release(self):raise AssertionError('unheld release')
ns['_live_price_fetch_locks']['solana']=Busy()
ns['_market_prices_fetch']=lambda *a:(_ for _ in ()).throw(AssertionError('duplicate upstream read'))
assert ns['_market_prices_for_pairs']('solana',['pair'])=={'pair':110},'lock timeout shares stale cache'
ns['_validated_market_pairs']=lambda c,p:p[:30] if c=='solana' else []
ns['_major_quote_snapshot']=lambda:{'prices':{'SOL':{'price':111,'observed_at':time.time()}}}
app=Flask(__name__)
with app.test_request_context('/?groups='+json.dumps({'solana':['pair']})+'&major=1'):
    response=ns['api_market_prices_batch']();data=response.json
    assert data['chains']['solana']['pair']==110
    assert data['observed_at']['solana']['pair']<data['server_ts']-2
    assert data['major']['prices']['SOL']['price']==111
    assert response.headers['Cache-Control']=='no-store'
print('PASS upstream failure retains real timestamp, single-flight timeout, native SOL and exact pool batch metadata')
