"""A Solana USDC tip checks the wallet's own rent floor before it sends.

Solana rejects a transaction that leaves the fee payer with more than zero
but less than a plain wallet's rent-exempt minimum (890,880 lamports):
"InsufficientFundsForRent, account_index 0". The tip code asked only for
20,000 lamports, so a trading wallet at 890,946 lamports looked ready, the
transfer went out, and Solana rejected it -- the member saw an error.

Now:
- every SOL check counts that floor (read from the chain, 890,880 fallback);
- with $0.20+ USDC to spare beside the tip, SOL is created from USDC FIRST
  and the tip goes through on the first send, with no rejected attempt;
- without it, the member is told exactly what to do (tip up to $X now, or
  add $Y USDC), not "Solana tip failed".
"""
import os, sqlite3, sys, tempfile
from decimal import Decimal
from unittest.mock import patch
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck='})
import app_entry  # noqa: E402
import portfolio_token_withdraw as m  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

sender, recipient = str(Keypair().pubkey()), str(Keypair().pubkey())
s_uid, r_uid = d.get_or_create_user(sender), d.get_or_create_user(recipient)
TRADING = str(Keypair().pubkey())
chain = {'lamports': 890_946, 'usdc_raw': 131_531}

def fake_rpc(_d, method, params, require_nonempty=False, preferred_url=None):
    if method == 'getMinimumBalanceForRentExemption':
        return (890_880 if params == [0] else 2_039_280), 'rpc'
    if method == 'getBalance':
        return {'value': chain['lamports']}, 'rpc'
    if method == 'getAccountInfo':
        return {'value': {'lamports': 2_039_280}}, 'rpc'   # recipient already has a USDC account
    raise AssertionError('unexpected RPC ' + method)

def fake_accounts(_d, owner, mint):
    return [{'pubkey': str(Keypair().pubkey()), 'account': {
        'owner': 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',
        'data': {'parsed': {'info': {'tokenAmount': {'amount': str(chain['usdc_raw']), 'decimals': 6}}}}}}]

m._fee_payer_rent_cache.update(value=0, at=0.0)
with patch.object(m, '_rpc_call_any', side_effect=fake_rpc), \
     patch.object(m, '_solana_source_accounts', side_effect=fake_accounts), \
     patch.object(d, '_get_trading_wallet_address', return_value=TRADING):
    ready = m._tip_solana_ready(d, sender, Decimal('0.10'), recipient)
check("the wallet's own rent floor counts: 890,880 + 20,000 lamports are needed, not 20,000",
      ready['required_lamports'] == 910_880)
check('...so a wallet at 890,946 lamports is NOT ready (it was, and Solana then rejected the tip)',
      ready['native_ready'] is False and ready['lamports'] == 890_946)
with patch.object(m, '_rpc_call_any', side_effect=RuntimeError('rpc down')):
    m._fee_payer_rent_cache.update(value=0, at=0.0)
    check('without an RPC answer the floor falls back to 890,880', m._fee_payer_rent_lamports(d) == 890_880)
src = open(os.path.join(ROOT, 'portfolio_token_withdraw.py'), encoding='utf-8').read()
transfer = src[src.index('def _solana_transfer('):src.index('def _evm_transfer(')]
check('the transfer itself checks the same floor before signing',
      'required_lamports = _fee_payer_rent_lamports(d) + 20_000' in transfer)

cl = app.test_client(); B = 'https://orcagent.fun'
with cl.session_transaction(base_url=B) as s:
    s['wallet'] = sender; s['user_id'] = s_uid; s['csrf_token'] = 'c' * 64
H = {'X-CSRF-Token': 'c' * 64}
sent, topups = [], []
def fake_transfer(_d, wallet, mint, to, amount, **kw):
    if chain['lamports'] < 910_880:
        raise m._SolanaPreflightError('Insufficient SOL', gas_shortfall=True, reason_code='insufficient_sol')
    sent.append(amount); return 'SIG' + str(len(sent)), float(amount)
def fake_topup(wallet, spare, target_sol=0.0035):
    topups.append((spare, target_sol)); chain['lamports'] = int(target_sol * 1e9)

def tip(amount):
    m._RECENT.clear()
    with patch.object(m, '_rpc_call_any', side_effect=fake_rpc), \
         patch.object(m, '_solana_source_accounts', side_effect=fake_accounts), \
         patch.object(m, '_tip_evm_candidates', return_value=([], [])), \
         patch.object(m, '_solana_transfer', side_effect=fake_transfer), \
         patch.object(m, '_record_tip', return_value=7), \
         patch.object(d, '_validate_csrf', return_value=True), \
         patch.object(d, '_get_trading_wallet_address', return_value=TRADING), \
         patch.object(d, '_gasless_solana_native_topup', side_effect=fake_topup, create=True):
        r = cl.post('/api/tip', json={'recipient_user_id': r_uid, 'amount': amount}, headers=H, base_url=B)
        return r.status_code, r.get_json()

code, body = tip('0.10')
check('$0.13 USDC and no spare SOL: a $0.10 tip is refused up front, nothing is sent',
      code == 400 and body['reason'] == 'needs_sol' and not sent and not topups)
check('...with what to do instead of "Solana tip failed"',
      'Add $0.17 USDC (or 0.002 SOL)' in body['error'] and 'Solana tip failed' not in body['error'])
chain.update(usdc_raw=5_000_000)
code, body = tip('4.90')
check('$5 USDC, $4.90 tip: told the maximum tip right now', code == 400 and 'tip up to $4.80 right now' in body['error'])
code, body = tip('1.00')
check('$5 USDC, $1 tip: SOL is made from spare USDC first, then the tip goes out on the FIRST send',
      code == 200 and body['ok'] and body['tx_hash'] == 'SIG1' and len(topups) == 1 and sent == [Decimal('1.00')])
check('...only from the USDC beside the tip, never the tip itself',
      topups[0][0] == Decimal('4.00') and topups[0][1] >= 0.0025)
raise SystemExit(0 if all(checks) else 1)
