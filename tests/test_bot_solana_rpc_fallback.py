"""Direct bot-only SOL/USDC balance reads, verified ATA and fail-closed behavior.
Offline tests. No wallet transaction, real RPC, or production database access.
"""
import ast
import base64
import binascii
import math
import threading
import time
from pathlib import Path
from unittest.mock import Mock
from solders.pubkey import Pubkey
ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'dashboard.py').read_text()
tree=ast.parse(SRC)
func=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
          and n.name=='_get_bot_solana_balances')
TOKEN='TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA'
USDC='EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
OWNER='Emj2Uktv12QjDZXRrvhHwHibJtkAMHxUGhzBK2AjXSGd'
ATA_PROGRAM='ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'
ATA,_=Pubkey.find_program_address([
 bytes(Pubkey.from_string(OWNER)),bytes(Pubkey.from_string(TOKEN)),
 bytes(Pubkey.from_string(USDC))],Pubkey.from_string(ATA_PROGRAM))
assert str(ATA)=='7ero64pAKXnrXwdUgmWVurMPGKAvsiQSJoH7VKNYuaH4'


def make(reader, ttl=3.0):
 ns=dict(threading=threading,time=time,base64=base64,binascii=binascii,
    requests=type('R',(),{'post':reader,'RequestException':OSError}),
    TOKEN_PROGRAM_ID=TOKEN,USDC_MINT=USDC,SOLANA_RPC_URL='',
    HELIUS_RPC='',SOLANA_RPC='https://api.mainnet-beta.solana.com',
    _bot_sol_balance_cache={},_bot_sol_balance_lock=threading.Lock(),
    _BOT_SOL_BALANCE_TTL=ttl,_BOT_SOL_READ_RPC='https://solana-rpc.publicnode.com')
 exec(compile(ast.Module(body=[func],type_ignores=[]),'dashboard.py','exec'),ns)
 return ns['_get_bot_solana_balances']


def reply(payload,status=200):
 return type('Response',(),{'status_code':status,'json':lambda self:payload})()


def account(value=1234567,owner=OWNER,mint=USDC,token_program=TOKEN):
 data=bytearray(bytes(Pubkey.from_string(mint))+bytes(Pubkey.from_string(owner))+value.to_bytes(8,'little')+bytes(93))
 data[108]=1  # SPL AccountState::Initialized; frozen accounts cannot spend
 assert len(data)==165
 return {'owner':token_program,'data':[base64.b64encode(data).decode(),'base64']}


def test_confirmed_direct_ata_balances_cache_and_zero():
 calls=[]
 def post(url,*,json,timeout):
  calls.append((url,json['method'],json['params']))
  if json['method']=='getBalance':return reply({'result':{'value':7000100}})
  return reply({'result':{'value':account()}})
 get=make(post)
 assert get(OWNER)==(0.0070001,1.234567)
 assert get(OWNER)==(0.0070001,1.234567)
 assert len(calls)==2
 assert all(url=='https://solana-rpc.publicnode.com' for url,_,_ in calls)
 assert [method for _,method,_ in calls]==['getBalance','getAccountInfo']
 assert calls[1][2][0]==str(ATA)
 assert all(p[2][-1].get('commitment')=='confirmed' for p in calls)
 print('PASS bot uses confirmed, direct, 3-second-cached SOL/USDC ATA reads (no indexed RPC)')
 no_ata=make(lambda url,*,json,timeout: reply({'result':{'value':
                      1000000 if json['method']=='getBalance' else None}}))
 assert no_ata(OWNER)==(0.001,0)
 print('PASS confirmed missing canonical spending ATA means zero SPENDABLE USDC')


def test_rate_limits_fail_closed_and_other_provider_recovers():
 calls=[]
 def post(url,*,json,timeout):
  calls.append((url,json['method']))
  if 'publicnode' in url:return reply({'error':{'code':429}},429)
  if json['method']=='getBalance':return reply({'result':{'value':30000000}})
  return reply({'result':{'value':account(2000000)}})
 assert make(post)(OWNER)==(0.03,2)
 assert ('https://api.mainnet-beta.solana.com','getAccountInfo') in calls
 print('PASS 429 uses configured read fallback with consistent provider snapshot')

 def blocked(url,*,json,timeout):return reply({'error':{'code':429}},429)
 try:make(blocked)(OWNER)
 except RuntimeError as exc:
  assert 'unavailable' in str(exc)
 else:raise AssertionError('429 was interpreted as zero')
 print('PASS complete RPC outage never masquerades as a zero or cached balance')


def test_untrusted_ata_wrong_owner_mint_or_format_rejected():
 for bad in (account(owner=str(Pubkey.new_unique())),
             account(mint=str(Pubkey.new_unique())),
             account(token_program='another-program'),
             {'owner':TOKEN,'data':['broken','base64']},
             dict(account(),data=[base64.b64encode(bytes(165)).decode(),'base64'])):
  def post(url,*,json,timeout):
   return reply({'result':{'value':0 if json['method']=='getBalance' else bad}})
  try:make(post)(OWNER)
  except RuntimeError:pass
  else:raise AssertionError('Invalid ATA data treated as confirmed balance')
 print('PASS no fabricated wallet ownership, mint, token program or malformed amount')


def test_bot_loop_wires_read_only_snapshot_and_backoff():
 assert 'us_sol, _bot_usdc_avail = _get_bot_solana_balances(_trading_wallet)' in SRC
 # SOL-funded: the network reserve is kept back from what the bot may spend.
 assert "us_solana_avail = max(0, us_sol - SOL_NETWORK_RESERVE) if _solana_base == 'SOL' else _bot_usdc_avail" in SRC
 assert 'stop_event.wait(12)' in SRC
 # Do not replace fresh recheck in trade execution or automatically transfer.
 assert '_get_solana_usdc_balance(trading_wallet)' in SRC
 assert '_get_user_sol(trading_wallet)' in SRC
 print('PASS bot reuses canonical snapshots, backs off failure and retains fresh buy checks')

if __name__=='__main__':
 test_confirmed_direct_ata_balances_cache_and_zero()
 test_rate_limits_fail_closed_and_other_provider_recovers()
 test_untrusted_ata_wrong_owner_mint_or_format_rejected()
 test_bot_loop_wires_read_only_snapshot_and_backoff()


def test_portfolio_rpc_429_recovers_only_provable_spendable_usdc():
    # Exercise real _get_solana_usdc_balance AST without importing production
    # dashboard (which would launch background services / require secrets).
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
            and n.name=='_get_solana_usdc_balance')
    calls=[]
    ns=dict(time=time,threading=threading,
            _sol_usdc_balance_lock=threading.Lock(),_sol_usdc_balance_cache={},
            _SOL_USDC_BALANCE_TTL=3.0,
            _solana_balance_rpc_pool=lambda:['https://api.mainnet-beta.solana.com'],
            _sum_usdc_from_entries=lambda entries:sum(float(i) for i in entries),
            USDC_MINT=USDC,TOKEN_PROGRAM_ID=TOKEN,TOKEN_2022_PROGRAM_ID='Token2022',
            _get_bot_solana_balances=lambda addr:(0.03,2.75))
    def post(url,*,json,timeout):
        calls.append(json['method'])
        return reply({'error':{'code':429}},429)
    ns['requests']=type('R',(),{'post':post})
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'dashboard.py','exec'),ns)
    assert ns['_get_solana_usdc_balance'](OWNER)==2.75
    assert calls==['getTokenAccountsByOwner']
    assert ns['_get_solana_usdc_balance'](OWNER)==2.75
    assert len(calls)==1
    print('PASS indexed RPC 429 recovers verified positive canonical spending USDC, cached briefly')
    ns['_sol_usdc_balance_cache'].clear()
    ns['_get_bot_solana_balances']=lambda addr:(0.03,0.0)
    indexed_before=len(calls)
    assert ns['_get_solana_usdc_balance'](OWNER,allow_stale=True)==0.0
    assert len(calls)==indexed_before, 'read-only Portfolio should not hit indexed RPC'
    try:ns['_get_solana_usdc_balance'](OWNER)
    except RuntimeError as exc:assert 'unavailable' in str(exc)
    else:raise AssertionError('indexed failure with absent ATA fabricated whole-wallet zero')
    ns['_get_bot_solana_balances']=lambda addr:(_ for _ in ()).throw(RuntimeError('RPC blocked'))
    try:ns['_get_solana_usdc_balance'](OWNER)
    except RuntimeError as exc:assert 'unavailable' in str(exc)
    else:raise AssertionError('RPC outage gave false balance')
    # Read-only Portfolio may reuse a recent confirmed value while providers
    # are throttled; money-moving callers keep the default fail-closed path.
    ns['_sol_usdc_balance_cache'][OWNER]=(time.time()-30,4.25)
    assert ns['_get_solana_usdc_balance'](OWNER,allow_stale=True)==4.25
    try:ns['_get_solana_usdc_balance'](OWNER)
    except RuntimeError:pass
    else:raise AssertionError('money-moving balance read accepted stale RPC data')
    print('PASS unavailable RPC never becomes zero; stale fallback is read-only opt-in')


def test_native_sol_read_tries_verified_publicnode_first():
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
            and n.name=='_get_user_sol')
    calls=[]
    def post(url,*,json,timeout):
        calls.append((url,json['method']))
        if url=='https://solana-rpc.publicnode.com':
            return reply({'result':{'value':37000000}})
        return reply({'error':{'code':429}},429)
    ns=dict(requests=type('R',(),{'post':post}),
         SOLANA_RPC_URL='',HELIUS_RPC='',CLAIM_SOL_RPCS=['https://api.mainnet-beta.solana.com'],
         SOLANA_RPC='https://api.mainnet-beta.solana.com',_PROXY_RPCS=[],
         _BOT_SOL_READ_RPC='https://solana-rpc.publicnode.com')
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'dashboard.py','exec'),ns)
    assert ns['_get_user_sol'](OWNER)==.037
    assert calls==[('https://solana-rpc.publicnode.com','getBalance')]
    print('PASS native SOL balance uses healthy confirmed public RPC rather than hammering 429 endpoints')

if __name__=='__main__':
 test_portfolio_rpc_429_recovers_only_provable_spendable_usdc()
 test_native_sol_read_tries_verified_publicnode_first()
