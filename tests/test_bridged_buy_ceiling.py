"""The buy that finishes on the far side of a bridge.

When a user buys a token on a chain they have no USDC on, the app bridges
funds over and completes the purchase minutes later, in
_execute_auto_buy_after_bridge(). That path swapped the FULL amount that
arrived and then charged 0.75% of it on top:

    _execute_evm_swap(..., str(amount_usdc), dest_chain)
    _charge_evm_txn_fee(..., amount_usdc, 'buy', dest_chain)

This is the worst wallet in the app to do that in. A bridge delivers exactly
the amount it was asked for and no more, so the fee had to come out of a
balance that was topped up to precisely this number -- and the gas for the
swap came out of the same place. The user's spend exceeded what they asked
for, out of money they had only just been given for the purchase itself.

It also told them the wrong thing afterwards: it logged "Bought X for
$<amount that arrived>" rather than what was actually bought.
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
WALLET = 'W_BRIDGED'
EVM    = '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
TOKEN  = '0xffffffffffffffffffffffffffffffffffffffff'

conn = sqlite3.connect(d.DB_FILE)
conn.execute('INSERT OR IGNORE INTO users (wallet_address) VALUES (?)', (WALLET,))
conn.execute("UPDATE users SET bsc_wallet_address=?, encrypted_private_key_bsc='ENC' "
             'WHERE wallet_address=?', (EVM, WALLET))
conn.commit()
UID = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.execute("INSERT INTO bridge_transactions (user_id, wallet, source_chain, dest_chain, "
             "token_in, token_out, amount_in, status) "
             "VALUES (?,?,?,?,?,?,?, 'bridge_filled')",
             (UID, WALLET, 'solana', 'base', 'USDC', 'USDC', 50.0))
conn.commit()
BID = conn.execute('SELECT MAX(id) FROM bridge_transactions').fetchone()[0]
conn.close()

class FakeKey:
    def __enter__(self): return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()

class FakeAcct:
    address = EVM
d._EvmAccount = type('A', (), {'from_key': staticmethod(lambda pk: FakeAcct())})
d._get_web3 = lambda chain: type('W3', (), {'to_checksum_address': staticmethod(lambda a: a)})()

# A bridge that delivered exactly the $50 it was asked to deliver.
d.get_evm_usdc_balance = lambda addr, chain='bsc': 50.0
d._ensure_evm_gas = lambda *a, **k: (True, '', None)
d.get_token_data = lambda a, **k: {'symbol': 'BRG', 'price': 0.02}
d._te_gas_usd = lambda chain: Decimal('0.35')
d._te_needs_sponsored_gas = lambda chain, addr: True

def fake_0x(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '985000000000000000',
            'transaction': {'gas': '200000', 'gasPrice': '10000000'}}
d._te_swap_provider = lambda chain: d.ZeroExProvider(fake_0x)

SWAPS, FEES, POSITIONS, LOGS = [], [], [], []
def fake_swap(wallet, pk, action, token, amount_str, chain='bsc'):
    SWAPS.append({'amount': amount_str, 'chain': chain})
    return True, '', '0xBRIDGEBUY'
d._execute_evm_swap = fake_swap
d._charge_evm_txn_fee = lambda pk, w, uid, sym, usdc, kind, chain='bsc', **kw: \
    FEES.append({'usdc': usdc})
d._upsert_open_position = lambda *a, **k: POSITIONS.append(a[3])
d.add_user_log = lambda w, m: LOGS.append(m)

def run():
    SWAPS.clear(); FEES.clear(); POSITIONS.clear(); LOGS.clear()
    d._execute_auto_buy_after_bridge(BID, UID, WALLET, 'base', TOKEN, 50.0)
    conn = sqlite3.connect(d.DB_FILE)
    try:
        r = conn.execute('SELECT auto_buy_status, auto_buy_result FROM bridge_transactions '
                         'WHERE id=?', (BID,)).fetchone()
    finally:
        conn.close()
    return {'status': r[0], 'result': json.loads(r[1] or '{}'),
            'swaps': list(SWAPS), 'fees': list(FEES),
            'positions': list(POSITIONS), 'logs': list(LOGS)}

out['engine'] = run()

d.TRADE_ENGINE_MANUAL_EVM = False
out['legacy'] = run()
d.TRADE_ENGINE_MANUAL_EVM = True

out['fee_rate'] = float(d.FEE_RATE_TXN)
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

eng, leg = out['engine'], out['legacy']

check('the bridged buy still completes', eng['status'] == 'done')
check('...and swapped once', len(eng['swaps']) == 1)

amount = float(eng['swaps'][0]['amount']) if eng['swaps'] else -1
check('it swaps LESS than the amount the bridge delivered, because gas and '
      'the fee came out of it — the whole point, in the one wallet that was '
      'funded to exactly this number and not a cent more',
      0 < amount < 50.0)
check('the fee is charged on what was bought rather than on everything that '
      'arrived', len(eng['fees']) == 1
      and abs(float(eng['fees'][0]['usdc']) - amount) < 1e-9)

check('the position records what was actually bought',
      bool(eng['positions']) and 0 < float(eng['positions'][0]['spend']) < 50.0)
check('...and so does the confirmation the user reads — telling them they '
      'bought $50 of something they hold less of is how a wrong PNL starts',
      any('$50.0' not in m for m in eng['logs'] if 'Bought' in m)
      and any('Bought' in m for m in eng['logs']))
check('the reported amount matches the swap, to the cent',
      abs(float(eng['result'].get('amount_usdc', -1)) - amount) < 1e-9)

check('the pre-engine path is still reachable, and is the one that swaps '
      'everything that arrived', leg['status'] == 'done'
      and len(leg['swaps']) == 1 and float(leg['swaps'][0]['amount']) == 50.0)
check('...and then charges the fee on top of all of it',
      len(leg['fees']) == 1 and float(leg['fees'][0]['usdc']) == 50.0)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
