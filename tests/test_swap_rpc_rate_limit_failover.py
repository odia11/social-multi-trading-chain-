"""RPC failover for Solana swap submission must survive provider throttling."""
import orcagent_solana as s

class Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
    def json(self):
        return self._body

checks=[]
def check(label, cond):
    checks.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + label)

original_rpcs=s.SOLANA_RPCS
original_post=s.requests.post
original_sleep=s.time.sleep
try:
    s.SOLANA_RPCS=['rpc-a','rpc-b']
    s.time.sleep=lambda *_: None

    calls=[]
    def rate_message_then_success(url, json, timeout):
        calls.append((url,json.get('method')))
        if url=='rpc-a':
            return Resp(200, {'error': {'code': -32007, 'message': 'Connection rate limits exceeded'}})
        return Resp(200, {'result':'sig-ok'})
    s.requests.post=rate_message_then_success
    out=s._rpc_post({'jsonrpc':'2.0','id':1,'method':'sendTransaction','params':['tx']},1)
    check('rate-limit message fails over even when provider uses an unexpected RPC code',
          out.get('result')=='sig-ok' and calls[:2]==[('rpc-a','sendTransaction'),('rpc-b','sendTransaction')])

    calls=[]
    def http_429_then_success(url, json, timeout):
        calls.append(url)
        return Resp(429,{}) if url=='rpc-a' else Resp(200,{'result':'sig-429-ok'})
    s.requests.post=http_429_then_success
    out=s._rpc_post({'jsonrpc':'2.0','id':1,'method':'sendTransaction','params':['tx']},1)
    check('HTTP 429 fails over to the next RPC', out.get('result')=='sig-429-ok' and calls==['rpc-a','rpc-b'])

    calls=[]
    real_error={'error': {'code': -32002, 'message':'Transaction simulation failed', 'data': {'err':'InsufficientFunds'}}}
    def preflight_rejection(url, json, timeout):
        calls.append(url)
        return Resp(200,real_error)
    s.requests.post=preflight_rejection
    out=s._rpc_post({'jsonrpc':'2.0','id':1,'method':'sendTransaction','params':['tx']},1)
    check('real transaction simulation errors are returned immediately, not hidden by failover',
          out==real_error and calls==['rpc-a'])

    calls=[]
    def both_busy(url, json, timeout):
        calls.append(url)
        return Resp(200,{'error': {'code':429,'message':'Too many requests'}})
    s.requests.post=both_busy
    try:
        s._rpc_post({'jsonrpc':'2.0','id':1,'method':'sendTransaction','params':['tx']},1)
        exhausted=False
    except RuntimeError as exc:
        exhausted='temporarily busy' in str(exc)
    check('sendTransaction gets a safe second pass of the same signed transaction',
          exhausted and calls==['rpc-a','rpc-b','rpc-a','rpc-b'])

    s.requests.post=lambda url,json,timeout: Resp(200,{'result':{'value':123}})
    calls_before=[]
    check('ordinary successful RPC reads remain unchanged',
          s._rpc_post({'jsonrpc':'2.0','id':1,'method':'getBalance','params':['wallet']},1)['result']['value']==123)
finally:
    s.SOLANA_RPCS=original_rpcs
    s.requests.post=original_post
    s.time.sleep=original_sleep

raise SystemExit(0 if all(checks) else 1)
