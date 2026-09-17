"""/api/manual_buy on Solana, once it runs through the engine.

WHAT CHANGED AND WHY IT WAS NOT OBVIOUS
This route was already funded in USDC, so it never had the currency bug the
copy-trade path did. What it had was subtler: it spent the typed amount IN
FULL and paid the Solana network fee out of the wallet's SOL, on top. So
"$50" meant fifty dollars of USDC plus whatever the network charged in a
second asset -- a real debit the user authorised nothing for, in a balance
the number on screen said nothing about.

It also had no balance reservation and no idempotency key. Its defence
against a double-click was a 15-second in-memory window, which is a UI guard:
it lives in one process, it is not a database constraint, and two requests
arriving together can both read it before either writes.

The companion test test_solana_buy_flow.py pins the pre-engine path that this
replaces and that still ships behind TRADE_ENGINE_SOLANA=0.
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
import json, sqlite3, sys, time
from decimal import Decimal
import dashboard as d

out = {}
d.app.config['TESTING'] = True
c = d.app.test_client()

WALLET = 'W_SOLENG'
MINT   = 'TokenMint3333333333333333333333333333333333'

conn = sqlite3.connect(d.DB_FILE)
conn.execute("INSERT OR IGNORE INTO users (wallet_address, encrypted_private_key) "
             "VALUES (?, 'ENC')", (WALLET,))
conn.execute("UPDATE users SET encrypted_private_key='ENC', min_trade_size=1, "
             "max_trade_size=200 WHERE wallet_address=?", (WALLET,))
conn.commit()
UID = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.close()

d._authenticated_wallet = lambda: WALLET
d._get_trading_wallet_address = lambda w: WALLET
d._get_user_sol = lambda a: 1.0
d._get_solana_usdc_balance = lambda a: 500.0
d._sol_price_usd = 150.0
d.get_token_data = lambda a, **k: {'symbol': 'SENG', 'price': 0.02, 'liquidity': 900000}
d._jupiter_quote = lambda i, o, amt: {
    'outAmount': '1000000000', 'otherAmountThreshold': '985000000',
    'priceImpactPct': '0.004'}
d._ensure_solana_gas = lambda w, pk: (True, '')

class FakeKey:
    def __enter__(self): return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, w: FakeKey()

import types
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
                        'signature': 'SIGENG'})
    return True, 'SIGENG', '', 1000.0, float(amount_str)
d._execute_user_swap_ex = fake_swap
d._charge_txn_fee = lambda *a, **k: FEES.append(a)

def buy(amount=50, idem=None):
    with d._rl_lock:
        d._rl_hits.clear()
    d._recent_solana_buys.clear()
    body = {'mint_address': MINT, 'amount_usdc': amount}
    r = c.post('/api/manual_buy', json=body)
    return r.status_code, r.get_json()

SWAPS.clear(); FEES.clear()
out['status'], out['body'] = buy(50)
out['swaps'] = list(SWAPS)
out['fees'] = list(FEES)

conn = sqlite3.connect(d.DB_FILE)
try:
    from trade_engine import ledger as L
    out['held'] = str(L.held_usd(conn, UID, 'solana'))
finally:
    conn.close()

pos = d.get_user_state(WALLET)['positions'].get(MINT) or {}
out['pos'] = {k: pos.get(k) for k in ('spend', 'base', 'symbol', 'entry_liquidity', 'sl_pct')}

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

body, swaps = out['body'], out['swaps']
check('the buy succeeds', out['status'] == 200 and body.get('ok') is True)
check('...and swapped once', len(swaps) == 1)
check('...funded in USDC', bool(swaps) and swaps[0]['base'] == 'USDC')

amount = float(swaps[0]['amount']) if swaps else -1
check('what is swapped is LESS than the $50 asked for, because the network '
      'fee now comes out of that $50 instead of out of the wallet\'s SOL on '
      'top of it — the debit the user never authorised',
      0 < amount < 50.0)
check('the response reports what was actually spent, not what was typed — a '
      'route that says $50 while swapping less is lying about the fill',
      abs(float(body.get('spend', -1)) - amount) < 1e-9)
check('no platform fee is charged on this leg, and the quote priced none, so '
      'nothing is double-counted', out['fees'] == [] and body.get('fee_collected') is False)

check('the reservation is released once the trade settles, so the rest of the '
      'balance is spendable again', out['held'] == '0')

pos = out['pos']
check('the position records the purchase, not the ceiling',
      pos.get('spend') is not None and 0 < float(pos['spend']) < 50.0)
check('...in the currency it was bought with, so the sell routes back the '
      'same way', pos.get('base') == 'USDC')
check('...and still carries the entry-liquidity snapshot this route has '
      'always taken — moving a route onto the engine must not quietly drop '
      'the bookkeeping around it',
      float(pos.get('entry_liquidity') or 0) == 900000.0)
check('...and the frozen stop-loss snapshot, which the exit monitor reads',
      pos.get('sl_pct') is not None)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
