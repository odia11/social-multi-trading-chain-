"""Latest native quotes use ticker, share a cache and identify failed symbols."""
import sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask
import auto_trading_bot_route as module
class Response:
    def __init__(self,data):self.data=data
    def json(self):return self.data
    def raise_for_status(self):pass
app=Flask(__name__)
d=SimpleNamespace(app=app)
module.install(d)
calls=[]
def get(url,**kwargs):
    calls.append(url)
    return Response({'open':'100'} if url.endswith('/stats') else {'price':'110'})
with patch.object(module.requests,'get',side_effect=get):
    first=d._major_quote_snapshot()
    assert first['prices']['SOL']['price']==110 and first['prices']['SOL']['change24h']==10
    assert first['prices']['SOL']['observed_at']>time.time()-1
    second=d._major_quote_snapshot()
    assert second==first and len(calls)==6
    time.sleep(1.05)
    third=d._major_quote_snapshot()
    assert len(calls)==9 and sum(u.endswith('/stats') for u in calls)==3
    observed=third['prices']['SOL']['observed_at']
    time.sleep(1.05)
    with patch.object(module.requests,'get',side_effect=module.requests.RequestException):
        failed=d._major_quote_snapshot()
    assert failed['stale'] and failed['prices']['SOL']['observed_at']==observed
    assert app.test_client().get('/api/home/major-prices').headers['Cache-Control']=='no-store'
print('PASS native ticker price, 1-second shared cache, stats reuse, outage preserves timestamp, no browser cache')
