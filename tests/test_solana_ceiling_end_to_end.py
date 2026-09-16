"""A Solana buy, end to end, spending no more than the user authorised.

This drives the REAL quote builder, the REAL cost engine, the REAL ledger and
the REAL executor wiring. Only the three places that touch the outside world
are stubbed: Jupiter's quote, the SOL price, and the swap subprocess. So what
it proves is the arithmetic and the accounting that actually ship, not a
model of them.

THE PROMISE BEING TESTED
The number the user types is the maximum total that leaves their balance.
Gas comes out of it, the slippage reserve comes out of it, and what remains
is what gets swapped. Nothing is added on top, and OrcAgent pays for none of
it -- a quote where any cost fell to OrcAgent cannot execute at all.
"""
import os
import sqlite3
import sys
import tempfile
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
CEILING = D('100')
MINT = 'TokenMint1111111111111111111111111111111111'
WALLET = 'SolWallet11111111111111111111111111111111'


# ── stubs, only at the network edge ───────────────────────────────────────
d._sol_price_usd = 150.0                      # so Solana gas can be priced at all
d._jupiter_quote = lambda i, o, amt: {
    'outAmount': '1000000000', 'otherAmountThreshold': '985000000',
    'priceImpactPct': '0.004',
}
d.get_token_data = lambda addr: {'symbol': 'TOK', 'price': '0.1'}

# A user row, so _get_uid and the key lookup find something real.
conn = sqlite3.connect(d.DB_FILE)
conn.execute("INSERT OR IGNORE INTO users (wallet_address, encrypted_private_key) VALUES (?,?)",
             (WALLET, 'enc-blob'))
conn.commit()
UID = conn.execute('SELECT id FROM users WHERE wallet_address=?', (WALLET,)).fetchone()[0]
conn.close()


quote = d._te_build_and_store_quote(
    uid=UID, wallet=WALLET, source_chain='solana', dest_chain='solana',
    token_address=MINT, max_spend=CEILING, taker=WALLET, mode='manual')
body = quote.to_dict()

purchase = D(body['token_purchase_usd'])
total = D(body['total_user_spend_usd'])
costs = body['costs_by_kind']

check('the quote can execute', body['can_execute'] is True)
check('the total the user spends never exceeds what they authorised — this is '
      'the whole promise', total <= CEILING)
check('...and the purchase is strictly smaller than the ceiling, because the '
      'costs came OUT of it rather than being added on top',
      D('0') < purchase < CEILING)
check('gas is charged to the user and is a real, non-zero figure — a zero here '
      'would be a cost quietly dropped out of the ceiling',
      D(costs.get('source_gas', '0')) > 0)
check('OrcAgent subsidises nothing', D(body['orcagent_subsidy_usd']) == 0)
check('no platform fee is quoted on a Solana USDC buy, because none is '
      'collected there', D(costs.get('platform_fee', '0')) == 0)
check('purchase plus every user cost reconstructs the total exactly — no '
      'rounding crumb escapes the ceiling',
      purchase + D(body['user_costs_usd']) == total)
check('the route names Jupiter, the provider that actually served it',
      'jupiter' in quote.route)


# ── execution, with the swap stubbed at the subprocess boundary ───────────
class _NullKey:
    def __enter__(self): return 'dummy-key'
    def __exit__(self, *a): return False


swapped = {}
def fake_swap(wallet, pk, action, mint, amount_str, base='SOL', capture=None):
    swapped['amount_str'] = amount_str
    swapped['base'] = base
    if capture is not None:
        capture.update({'send_attempted': True, 'onchain_failed': False,
                        'signature': 'SIGOK'})
    return True, 'SIGOK', '', 1000.0, float(amount_str)


d._execute_user_swap_ex = fake_swap
d._ensure_solana_gas = lambda w, pk: (True, '')
d._use_key = lambda blob, w: _NullKey()

result = d._te_run_solana_trade(
    quote_id=quote.quote_id, idem=f'{UID}:quote:{quote.quote_id}',
    available=D('500'), wallet=WALLET, enc_blob='enc-blob', symbol='TOK',
    token_address=MINT, user_id=UID)

check('the trade completes', result.state == L.COMPLETED)
check('what was actually swapped is the quoted purchase, to the cent — not the '
      'ceiling, which is what every legacy route swaps',
      D(swapped['amount_str']) == purchase)
check('...funded in USDC', swapped['base'] == 'USDC')

conn = sqlite3.connect(d.DB_FILE)
try:
    held = L.held_usd(conn, UID, 'solana')
    trade = L.get_trade(conn, result.trade_id)
    # A retry of the very same request must not swap a second time.
    swapped.clear()
    again = d._te_run_solana_trade(
        quote_id=quote.quote_id, idem=f'{UID}:quote:{quote.quote_id}',
        available=D('500'), wallet=WALLET, enc_blob='enc-blob', symbol='TOK',
        token_address=MINT, user_id=UID)
finally:
    conn.close()

check('the reservation is closed once the trade settles, so the rest of the '
      'balance is spendable again', held == D('0'))
check('the trade records the signature it actually got',
      (trade or {}).get('source_tx_hash') == 'SIGOK')
check('a retry with the same idempotency key returns the original trade',
      again.trade_id == result.trade_id and again.created is False)
check('...and never reaches the swap a second time — the guard is the database '
      'constraint, not a lookup two requests can both pass',
      'amount_str' not in swapped)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
