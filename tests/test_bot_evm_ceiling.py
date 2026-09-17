"""The autonomous bot's EVM entry, and the money it used to spend twice over.

WHAT WAS WRONG
_bot_scan_evm_entry() swapped the user's configured trade size IN FULL and
then charged 0.75% of it on top:

    _execute_evm_swap(..., str(min_trade_usdc), chain)
    _charge_evm_txn_fee(pk, ..., min_trade_usdc, 'buy', chain)

So a user who set their size to $10 had $10 swapped, $0.075 taken separately,
and gas on top of both -- every entry, on five chains, running unattended.
That is the exact thing the engine exists to prevent, and the bot was the one
buy path still doing it. It also had no balance reservation (two overlapping
cycles could claim the same USDC) and no idempotency key.

The position it opened was wrong in the same direction: it recorded
min_trade_usdc as the spend and min_trade_usdc/price as the amount, so every
bot position overstated what was bought and understated what it cost.
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
WALLET = 'W_BOT'
EVM    = '0xcccccccccccccccccccccccccccccccccccccccc'
MINT   = '0xdddddddddddddddddddddddddddddddddddddddd'

conn = sqlite3.connect(d.DB_FILE)
conn.execute('INSERT OR IGNORE INTO users (wallet_address) VALUES (?)', (WALLET,))
conn.execute("UPDATE users SET bsc_wallet_address=?, encrypted_private_key_bsc='ENC' "
             'WHERE wallet_address=?', (EVM, WALLET))
conn.commit()
UID = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.close()

# ── the candidate the scanner hands the bot ──
d._get_scanner_cached = lambda *a, **k: [{
    'chain': 'base', 'mint': MINT, 'symbol': 'BOTX',
    'market_cap': 5_000_000, 'liquidity_usd': 2_000_000,
    'volume_24h': 900_000, 'pair_created_at': (time.time() - 86400) * 1000,
}]
d.get_token_data = lambda a, fast=False: {
    'symbol': 'BOTX', 'price': 0.01, 'change5m': 40.0, 'change1h': 40.0,
    'volume5m': 50_000, 'volume1h': 100_000,
}
d._check_evm_honeypot = lambda mint, chain: {'ok': True, 'is_honeypot': False,
                                             'sell_tax': 0, 'no_provider': False}
d._te_gas_usd = lambda chain: Decimal('0.35')
d._te_needs_sponsored_gas = lambda chain, addr: True
d.get_evm_usdc_balance = lambda addr, chain='bsc': 500.0
d._ensure_evm_gas = lambda *a, **k: (True, '', None)

POSITIONS = []
d._upsert_open_position = lambda *a, **k: POSITIONS.append((a[3], k))

def fake_0x(sell, buy, amount, taker, chain):
    return {'buyAmount': '1000000000000000000', 'minBuyAmount': '985000000000000000',
            'transaction': {'gas': '200000', 'gasPrice': '10000000'}}
d._te_swap_provider = lambda chain: d.ZeroExProvider(fake_0x)

class FakeKey:
    def __enter__(self): return 'PK'
    def __exit__(self, *a): return False
d._use_key = lambda blob, wallet: FakeKey()

class FakeAcct:
    address = EVM
d._EvmAccount = type('A', (), {'from_key': staticmethod(lambda pk: FakeAcct())})

SWAPS, FEES = [], []
def fake_swap(wallet, pk, action, token, amount_str, chain='bsc'):
    SWAPS.append({'action': action, 'amount': amount_str, 'chain': chain})
    return True, '', '0xBOT'
d._execute_evm_swap = fake_swap
d._charge_evm_txn_fee = lambda pk, w, uid, sym, usdc, kind, chain='bsc', **kw: \
    FEES.append({'usdc': usdc, 'kind': kind})

def scan(positions=None):
    SWAPS.clear(); FEES.clear(); POSITIONS.clear()
    return d._bot_scan_evm_entry(
        UID, WALLET, positions if positions is not None else {}, 'base', 'ENC',
        10.0, frozenset(), 5.0, None, False, 'bot')

# ── the engine path (default) ──
out['bought'] = scan()
out['swaps'] = list(SWAPS)
out['fees'] = list(FEES)
out['positions'] = [(p, {k: v for k, v in kw.items() if k in ('source', 'chain')})
                    for p, kw in POSITIONS]
out['fee_rate'] = float(d.FEE_RATE_TXN)

# ── the pre-engine path, for comparison ──
d.TRADE_ENGINE_BOT_EVM = False
out['legacy_bought'] = scan()
out['legacy_swaps'] = list(SWAPS)
out['legacy_fees'] = list(FEES)
d.TRADE_ENGINE_BOT_EVM = True

# ── a balance that cannot cover the configured size ──
d.get_evm_usdc_balance = lambda addr, chain='bsc': 2.0
out['poor_bought'] = scan()
out['poor_swaps'] = list(SWAPS)
d.get_evm_usdc_balance = lambda addr, chain='bsc': 500.0

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
d_fee_rate = out['fee_rate']
check('the bot still enters a qualifying candidate', out['bought'] is True)
check('...exactly once', len(swaps) == 1)

amount = float(swaps[0]['amount']) if swaps else -1
check('what it swaps is strictly LESS than the configured size, because gas '
      'and the fee came out of it — the old path swapped all $10 and then '
      'charged more on top',
      0 < amount < 10.0)
# The fee is still collected on EVM -- it is a real separate transfer there,
# unlike Solana -- but it is charged on the PURCHASE, which the quote already
# subtracted from the ceiling, instead of on the full configured size.
fee_usd = float(out['fees'][0]['usdc']) if out['fees'] else -1
check('the fee is charged on what was bought, not on the size that was asked '
      'for — 0.75% of a number the user never agreed to spend is exactly the '
      'overcharge being removed',
      len(out['fees']) == 1 and abs(fee_usd - amount) < 1e-9)
check('and the whole entry — swap plus fee — still fits inside the configured '
      'size, which is the promise: what was set is the maximum, not the '
      'starting point',
      amount + fee_usd * d_fee_rate <= 10.0 + 1e-9)

pos = out['positions']
check('the position is still recorded as the bot\'s', bool(pos) and pos[0][1].get('source') == 'bot')
check('...on the right chain', bool(pos) and pos[0][1].get('chain') == 'base')
check('...and records what was actually bought, not the size that was asked '
      'for — a position that overstates its spend poisons every PNL after it',
      bool(pos) and 0 < float(pos[0][0]['spend']) < 10.0)

check('the pre-engine path is still reachable by flag, and is the one that '
      'swaps the full size', out['legacy_bought'] is True
      and len(out['legacy_swaps']) == 1
      and float(out['legacy_swaps'][0]['amount']) == 10.0)
check('...and charges the fee separately on top of it, which is the behaviour '
      'being replaced', len(out['legacy_fees']) == 1)

check('a wallet that cannot cover the configured size does not enter at all, '
      'rather than entering smaller than the user set',
      out['poor_bought'] is False and out['poor_swaps'] == [])

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
