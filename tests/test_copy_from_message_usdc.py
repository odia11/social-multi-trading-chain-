"""The "⚡ Copy Trade" button under a shared trade card.

WHAT IT USED TO DO
The page read amount_sol off the shared trade card -- the size the ORIGINAL
trader used -- and POSTed it as the copier's spend:

    body:JSON.stringify({token_address, entry_price, amount_sol:amtSol})
    ...
    spend = round(min(amount_sol, us_sol), 4)
    _buy_and_get_realized(wallet, _pk, token_address, spend, price)   # SOL

Three things wrong in one number. It was someone else's position size, so
copying a whale spent like a whale. It was SOL, in an app that funds every
other trade in USDC, so a copier holding only USDC was told to go buy SOL.
And it came from the browser, so the spend was whatever the request said it
was, bounded only by the wallet's balance.

It also called _charge_txn_fee(bundled=True) unconditionally -- booking a fee
and paying a 20% referral cut on money that the swap may never have
collected. That bug was fixed in _solana_buy_flow() and this route, being a
second copy of the same logic, never got the fix.

So this endpoint now does none of it itself: it looks up what the copier
configured and hands the whole thing to the one Solana buy flow.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


PROBE = r'''
import json, sqlite3, sys, types
from decimal import Decimal
import dashboard as d

out = {}
d.app.config['TESTING'] = True
c = d.app.test_client()

WALLET = 'W_CFM'
MINT   = 'TokenMint4444444444444444444444444444444444'

conn = sqlite3.connect(d.DB_FILE)
conn.execute("INSERT OR IGNORE INTO users (wallet_address, encrypted_private_key) "
             "VALUES (?, 'ENC')", (WALLET,))
# What the copier configured: $7. The card below claims 2.5 SOL (~$375).
conn.execute("UPDATE users SET encrypted_private_key='ENC', copy_amount=7.0, "
             "min_trade_size=1, max_trade_size=200 WHERE wallet_address=?", (WALLET,))
conn.commit()
UID = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.close()

d._authenticated_wallet = lambda: WALLET
d._get_trading_wallet_address = lambda w: WALLET
d._get_user_sol = lambda a: 1.0
d._get_solana_usdc_balance = lambda a: 500.0
d._sol_price_usd = 150.0
d.get_token_data = lambda a, **k: {'symbol': 'CFM', 'price': 0.05, 'liquidity': 800000}
d._jupiter_quote = lambda i, o, amt: {
    'outAmount': '1000000000', 'otherAmountThreshold': '985000000',
    'priceImpactPct': '0.004'}
d._ensure_solana_gas = lambda w, pk: (True, '')

class FakeKey:
    def __enter__(self): return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, w: FakeKey()

fake_solders = types.ModuleType('solders.keypair')
class _KP:
    @staticmethod
    def from_base58_string(pk):
        return types.SimpleNamespace(pubkey=lambda: WALLET)
fake_solders.Keypair = _KP
sys.modules['solders.keypair'] = fake_solders

SWAPS, FEES = [], []
def fake_swap(wallet, pk, action, mint, amount_str, base='SOL', capture=None):
    SWAPS.append({'amount': amount_str, 'base': base})
    if capture is not None:
        capture.update({'send_attempted': True, 'onchain_failed': False,
                        'signature': 'SIGCFM'})
    return True, 'SIGCFM', '', 1000.0, float(amount_str)
d._execute_user_swap_ex = fake_swap
d._charge_txn_fee = lambda *a, **k: FEES.append(a)

def post(body):
    with d._rl_lock:
        d._rl_hits.clear()
    d._recent_solana_buys.clear()
    # A real browser sends this; once the session has a token, so must we.
    tok = (c.get('/api/csrf-token').get_json() or {}).get('token', '')
    r = c.post('/api/trades/copy-from-message', json=body,
               headers={'X-CSRF-Token': tok})
    return r.status_code, r.get_json()

# The old page's body, sent verbatim: a whale-sized SOL amount off the card.
SWAPS.clear(); FEES.clear()
out['status'], out['body'] = post({'token_address': MINT, 'entry_price': 0.05,
                                   'amount_sol': 2.5})
out['swaps'] = list(SWAPS)
out['fees'] = list(FEES)

pos = d.get_user_state(WALLET)['positions'].get(MINT) or {}
out['pos'] = {k: pos.get(k) for k in ('spend', 'base', 'symbol')}

# And with no amount at all, which is what the page sends now.
SWAPS.clear()
d.get_user_state(WALLET)['positions'].pop(MINT, None)
conn = sqlite3.connect(d.DB_FILE)
conn.execute('DELETE FROM open_positions WHERE user_id=?', (UID,))
conn.commit(); conn.close()
out['bare_status'], out['bare'] = post({'token_address': MINT, 'entry_price': 0.05})
out['bare_swaps'] = list(SWAPS)

print('@@@' + json.dumps(out, default=str))
'''

env = dict(os.environ)
env.update({'DATA_DIR': tempfile.mkdtemp(), 'SECRET_KEY': 'x' * 32,
            'ENCRYPTION_KEY': 'K' * 43 + '=', 'DEV': '1'})
p = subprocess.run([sys.executable, '-c', PROBE], cwd=REPO, env=env,
                   capture_output=True, text=True, timeout=300)
if '@@@' not in p.stdout:
    print(p.stdout[-3000:]); print(p.stderr[-3000:])
    sys.exit('probe did not report')
out = json.loads(p.stdout.split('@@@', 1)[1].splitlines()[0])

swaps = out['swaps']
check('the copy succeeds', out['status'] == 200 and out['body'].get('ok') is True)
check('...and swapped once', len(swaps) == 1)
check('...in USDC, not SOL — a copier holding only USDC could not use this '
      'button at all before', bool(swaps) and swaps[0]['base'] == 'USDC')

amount = float(swaps[0]['amount']) if swaps else -1
check('a client-sent amount_sol of 2.5 (~$375 of SOL) is IGNORED — the spend '
      'is the copier\'s own configured $7, which is the whole point of a '
      'copy size being a setting rather than a request field',
      0 < amount <= 7.0)
check('...and it is strictly under $7, because the costs came out of it',
      0 < amount < 7.0)
check('no fee is booked on a Solana USDC buy, where none is collected — the '
      'old route wrote one unconditionally and paid a referral cut on it',
      out['fees'] == [])

pos = out['pos']
check('the position records the purchase', pos.get('spend') is not None
      and 0 < float(pos['spend']) < 7.0)
check('...in the currency it was bought with', pos.get('base') == 'USDC')

check('a request with no amount field at all — what the page sends now — '
      'still buys, at the same configured size',
      out['bare_status'] == 200 and len(out['bare_swaps']) == 1
      and abs(float(out['bare_swaps'][0]['amount']) - amount) < 1e-9)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
