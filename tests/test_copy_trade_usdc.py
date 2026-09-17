"""Copying a Solana trader spends USDC, through the engine, at the size they set.

WHY THIS EXISTS
_trigger_copy_buy() read copy_amount -- a dollar figure, the same column the
EVM copy path spends as USDC and the same one Settings labels in dollars --
and spent it as SOL:

    spend = round(min(float(c_copy_amount), c_sol * 0.9), 4)

So a copier who set 10 did not buy 10 dollars of anything. They asked for 10
SOL, were capped at 90% of their balance, and the cap became the trade size.
The number they chose never applied at all, and the wallet it drained was the
SOL one they need for network fees. It also gated entry on `c_sol < 0.01`, so
a copier holding nothing but USDC -- the funding currency everywhere else in
this app -- was skipped every single time with "insufficient SOL".

This drives the real function against a real database with only the network
edges stubbed.
"""
import os
import sqlite3
import sys
import tempfile
import time
from decimal import Decimal

_DATA = tempfile.mkdtemp()
os.environ.setdefault('DATA_DIR', _DATA)
os.environ.setdefault('SECRET_KEY', 'x' * 32)
os.environ.setdefault('ENCRYPTION_KEY', 'K' * 43 + '=')
os.environ.setdefault('DEV', '1')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dashboard as d                                              # noqa: E402
from trade_engine import ledger as L                               # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

D = Decimal
LEADER = 'LeaderWallet1111111111111111111111111111111'
COPIER = 'CopierWallet1111111111111111111111111111111'
MINT = 'TokenMint2222222222222222222222222222222222'


# ── stubs, only at the network edge ───────────────────────────────────────
d._sol_price_usd = 150.0
d._jupiter_quote = lambda i, o, amt: {
    'outAmount': '1000000000', 'otherAmountThreshold': '985000000',
    'priceImpactPct': '0.004',
}
d.get_token_data = lambda addr: {'symbol': 'TOK', 'price': '0.1'}
d._check_price_impact = lambda mint, spend, input_mint=None, input_decimals=9: {
    'ok': True, 'price_impact_pct': 0.004,
    '_seen': impact_seen.update({'input_mint': input_mint, 'spend': spend}),
}
impact_seen = {}
d._get_trading_wallet_address = lambda w: w
d._ensure_solana_gas = lambda w, pk: (True, '')


class _NullKey:
    def __enter__(self): return 'dummy-key'
    def __exit__(self, *a): return False


d._use_key = lambda blob, w: _NullKey()

swapped = {}
def fake_swap(wallet, pk, action, mint, amount_str, base='SOL', capture=None):
    swapped['amount_str'] = amount_str
    swapped['base'] = base
    if capture is not None:
        capture.update({'send_attempted': True, 'onchain_failed': False,
                        'signature': 'SIGCOPY'})
    return True, 'SIGCOPY', '', 1000.0, float(amount_str)


d._execute_user_swap_ex = fake_swap

# The copier's USDC. Deliberately far more SOL-shaped than USD-shaped: 40 is
# a fine number of dollars and an absurd number of SOL, so a route that still
# thinks in SOL cannot accidentally pass.
usdc_balance = {'v': 40.0}
d._get_solana_usdc_balance = lambda addr: usdc_balance['v']
# Zero SOL beyond fees. Under the old gate this alone skipped every copy.
d._get_user_sol = lambda addr: 0.0

fees_charged = []
d._charge_txn_fee = lambda *a, **k: fees_charged.append(a)


# ── a leader with an open position, and a copier following them ───────────
conn = sqlite3.connect(d.DB_FILE)
conn.execute("INSERT OR IGNORE INTO users (wallet_address, encrypted_private_key) VALUES (?,?)",
             (LEADER, 'enc-leader'))
conn.execute("INSERT OR IGNORE INTO users (wallet_address, encrypted_private_key, copy_source, "
             "copy_amount, min_trade_size, max_positions, daily_loss_limit) "
             "VALUES (?,?,?,?,?,?,?)",
             (COPIER, 'enc-copier', LEADER, 10.0, 1.0, 5, 50.0))
conn.commit()
C_UID = conn.execute('SELECT id FROM users WHERE wallet_address=?', (COPIER,)).fetchone()[0]
L_UID = conn.execute('SELECT id FROM users WHERE wallet_address=?', (LEADER,)).fetchone()[0]
conn.close()

d._upsert_open_position(L_UID, LEADER, MINT, {
    'amount': 100.0, 'buy_price': 0.1, 'spend': 10.0, 'symbol': 'TOK',
    'opened_at': time.time()}, source='manual', chain='solana')


def run_copy():
    """Fire the real trigger and wait for its daemon thread to finish."""
    swapped.clear()
    before = len(d.get_user_state(COPIER)['positions'])
    d._trigger_copy_buy(LEADER, MINT, 0.1, 'TOK', 50000.0, chain='solana')
    for _ in range(100):
        if swapped or len(d.get_user_state(COPIER)['positions']) != before:
            break
        time.sleep(0.05)
    time.sleep(0.3)   # let the position write land


run_copy()

check('the copy actually happens for a wallet holding only USDC — under the '
      'old SOL gate this was skipped every time with "insufficient SOL"',
      bool(swapped))
check('...funded in USDC', swapped.get('base') == 'USDC')
check('the copier is quoted on the USDC route, not the SOL one — gating on a '
      'pool the swap never touches is how a tradeable token looks illiquid',
      impact_seen.get('input_mint') == d.USDC_MINT)
check('copy_amount is read as DOLLARS: 10 means ten dollars, and the amount '
      'swapped is at most that, not 10 SOL',
      swapped.get('amount_str') and D(swapped['amount_str']) <= D('10'))
check('...and costs came OUT of it, so the swap is strictly smaller than the '
      'ceiling rather than equal to it',
      swapped.get('amount_str') and D(swapped['amount_str']) < D('10'))
check('no platform fee is charged — a USDC-funded Solana buy collects none, '
      'and the quote was priced at zero to match', fees_charged == [])

state = d.get_user_state(COPIER)['positions'].get(MINT) or {}
check('the position is recorded as a copy', state.get('source') == 'copy')
check('...and attributed to the leader', state.get('copy_of_wallet') == LEADER)

conn = sqlite3.connect(d.DB_FILE)
try:
    check('the reservation is released once it settles',
          L.held_usd(conn, C_UID, 'solana') == D('0'))
finally:
    conn.close()


# ── the same entry seen twice must not buy twice ──────────────────────────
d.get_user_state(COPIER)['positions'][MINT]['amount'] = 0.0   # pretend not held
run_copy()
check('seeing the SAME leader entry again does not buy a second time — the '
      'guard is the idempotency key on the leader\'s entry, not a position '
      'lookup that a second trigger can race',
      not swapped)


# ── a ceiling that does not fit is refused, never trimmed ─────────────────
usdc_balance['v'] = 3.0          # less than the 10 the copier set aside
d._upsert_open_position(L_UID, LEADER, MINT, {
    'amount': 100.0, 'buy_price': 0.1, 'spend': 10.0, 'symbol': 'TOK',
    'opened_at': time.time() + 60}, source='manual', chain='solana')
d.get_user_state(COPIER)['positions'][MINT]['amount'] = 0.0
run_copy()
check('a copier who cannot cover the size they set is skipped, NOT quietly '
      'bought in at whatever they happen to hold — the number they chose is '
      'the trade, and a smaller one is a different trade they did not pick',
      not swapped)


# ── the flag disables copying rather than falling back ────────────────────
usdc_balance['v'] = 40.0
_orig_flag = d.TRADE_ENGINE_SOLANA
d.TRADE_ENGINE_SOLANA = False
try:
    run_copy()
    check('with the engine off, Solana copying stops instead of falling back '
          'to the SOL-denominated path it replaced', not swapped)
finally:
    d.TRADE_ENGINE_SOLANA = _orig_flag

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
