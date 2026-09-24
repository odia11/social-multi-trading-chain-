"""A wallet funded only in USDC must be able to SELL what the bot bought.

Buys in USDC go through Jupiter Ultra gasless, so the auto-trading bot
happily opens positions with zero SOL. Sells used to always take the legacy
executor, which pays the network fee in SOL -- so such a position could not
be closed (stop-loss, take-profit, manual sell) until the user deposited SOL.
Low-SOL USDC sells now go gasless too; wallets with enough SOL keep the
legacy path unchanged."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import solana_gasless_trading as g
from solders.keypair import Keypair

MINT = 'TokenMint1111111111111111111111111111111111'
KP = Keypair()
PK = str(KP)
ADDR = str(KP.pubkey())

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

def make(sol=0.0, balance_raw=5_000_000, decimals=6, gasless=True, code=None):
    calls = {'original': [], 'orders': [], 'executed': 0}
    def original(*a):
        calls['original'].append(a)
        return True, 'LEGACYSIG', '', 1.0, 1.0
    d = SimpleNamespace(_execute_user_swap_ex=original, FEE_RATE_TXN=0.0075,
                        _redact_keys=lambda s: s, SOLANA_RPC_URL='http://rpc')
    def rpc(_d, method, params):
        if method == 'getBalance':
            return {'value': int(sol * 1_000_000_000)}
        if method == 'getTokenAccountsByOwner':
            assert params[0] == ADDR and params[1] == {'mint': MINT}
            return {'value': [{'account': {'data': {'parsed': {'info': {'tokenAmount': {
                'amount': str(balance_raw), 'decimals': decimals}}}}}}]}
        if method == 'getTokenSupply':
            return {'value': {'decimals': decimals}}
        raise AssertionError(method)
    class Resp:
        def __init__(self, data): self.data, self.ok, self.status_code = data, True, 200
        def json(self): return self.data
    def get(url, params=None, headers=None, timeout=None):
        calls['orders'].append(params)
        if code is not None:
            return Resp({'errorCode': code, 'errorMessage': 'too small'})
        return Resp({'transaction': 'TX', 'requestId': 'R', 'gasless': gasless,
                     'inAmount': params['amount'], 'outAmount': '2990000'})
    def post(url, json=None, headers=None, timeout=None):
        calls['executed'] += 1
        return Resp({'status': 'Success', 'signature': 'ULTRASIG',
                     'inputAmountResult': json and '5000000', 'outputAmountResult': '2985000'})
    g._rpc = rpc
    g.requests = SimpleNamespace(get=get, post=post, RequestException=Exception)
    g._sign_for_taker = lambda pk, tx: 'SIGNED'
    g._api_key = lambda: 'KEY'
    g._referral_account = lambda: ''
    g.install(d)
    return d, calls

# Enough SOL: the legacy executor, exactly as before.
d, c = make(sol=0.05)
r = d._execute_user_swap_ex('W', PK, 'sell', MINT, '0', 'USDC', None)
check('USDC sell with enough SOL keeps the legacy executor', r[1] == 'LEGACYSIG' and len(c['original']) == 1 and not c['orders'])

# No SOL: gasless Ultra sell of the whole balance into USDC.
d, c = make(sol=0.0)
cap = {}
r = d._execute_user_swap_ex('W', PK, 'sell', MINT, '0', 'USDC', cap)
o = c['orders'][0] if c['orders'] else {}
check('zero-SOL USDC sell goes through Jupiter Ultra', r[0] is True and r[1] == 'ULTRASIG' and not c['original'])
check('sell order is token -> USDC for the full raw balance',
      o.get('inputMint') == MINT and o.get('outputMint') == g._USDC and o.get('amount') == '5000000' and o.get('taker') == ADDR)
check('returns realized token amount and USDC received', r[3] == 5.0 and abs(r[4] - 2.985) < 1e-9)
check('capture reports the gasless route', cap.get('gasless') is True)

# Percent and explicit amounts resolve like orcagent_solana.py.
d, c = make(sol=0.0)
d._execute_user_swap_ex('W', PK, 'sell', MINT, '50%', 'USDC', None)
check('"50%" sells half of the raw balance', c['orders'][0]['amount'] == '2500000')
d, c = make(sol=0.0)
d._execute_user_swap_ex('W', PK, 'sell', MINT, '99', 'USDC', None)
check('an amount above the balance is clamped to the balance', c['orders'][0]['amount'] == '5000000')

# Nothing held: fails cleanly, no order placed.
d, c = make(sol=0.0, balance_raw=0)
r = d._execute_user_swap_ex('W', PK, 'sell', MINT, '0', 'USDC', None)
check('empty balance fails without placing an order', r[0] is False and not c['orders'] and 'nothing to sell' in r[2])

# Jupiter offers no gasless route for a zero-SOL wallet: refuse, don't send.
d, c = make(sol=0.0, gasless=False)
r = d._execute_user_swap_ex('W', PK, 'sell', MINT, '0', 'USDC', None)
check('non-gasless order for a zero-SOL wallet is refused', r[0] is False and c['executed'] == 0 and 'gasless' in r[2])

# Below Jupiter's gasless minimum: a clear, actionable message.
d, c = make(sol=0.0, code=3)
r = d._execute_user_swap_ex('W', PK, 'sell', MINT, '0', 'USDC', None)
check('below-minimum sale explains how much SOL to add', r[0] is False and 'SOL to the trading wallet to sell it' in r[2])

# SOL-based positions are untouched.
d, c = make(sol=0.0)
d._execute_user_swap_ex('W', PK, 'sell', MINT, '0', 'SOL', None)
check('SOL-based sells always keep the legacy executor', len(c['original']) == 1 and not c['orders'])

# Buys still go gasless regardless of SOL.
d, c = make(sol=0.05)
g._token_decimals = lambda _d, m: 6
r = d._execute_user_swap_ex('W', PK, 'buy', MINT, '2', 'USDC', None)
check('USDC buys still go through Ultra', not c['original'] and c['orders'][0]['inputMint'] == g._USDC and c['orders'][0]['amount'] == '2000000')

raise SystemExit(0 if all(checks) else 1)
