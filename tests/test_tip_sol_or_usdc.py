"""Users tip each other in SOL or in USDC.

Since the move to native SOL (#155) /api/tip only took SOL ("Refresh the app:
tips now use SOL"), so USDC tips did not work at all. The tip sheet now has a
SOL | USDC switch:
- SOL: a native transfer; the network fee comes out of the amount.
- USDC: a Solana USDC (SPL) transfer of the full amount; the sender's SOL
  pays the network fee and, if needed, the recipient's USDC account rent.
Both go to the recipient's OrcAgent trading wallet and are recorded in the
tip ledger with their own currency; notifications show "5.00 USDC".
"""
import os, sqlite3, sys, tempfile
from decimal import Decimal
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(), 'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
import portfolio_token_withdraw as ptw  # noqa: E402
import sol_native_payments  # noqa: E402
import tip_experience  # noqa: E402
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

alice_w, bob_w = str(Keypair().pubkey()), str(Keypair().pubkey())
alice, bob = d.get_or_create_user(alice_w), d.get_or_create_user(bob_w)
trading = {alice_w: str(Keypair().pubkey()), bob_w: str(Keypair().pubkey())}
d._get_trading_wallet_address = lambda w: trading.get(w, '')
sent = []
def fake_spl(dd, wallet, token, to, amount, allow_user_funded_gas=False):
    sent.append(('spl', wallet, token, to, amount, allow_user_funded_gas)); return 'SPLSIG' + str(len(sent)), float(amount)
def fake_native(dd, wallet, to, amount, request_id=None):
    sent.append(('sol', wallet, to, amount)); return 'SOLSIG' + str(len(sent)), float(amount) - 0.000005
ptw._solana_transfer = fake_spl
sol_native_payments.native_transfer = fake_native

BASE, CSRF = 'https://orcagent.fun', 't' * 40
c = app_entry.app.test_client()
with c.session_transaction(base_url=BASE) as s:
    s['wallet'] = alice_w; s['csrf_token'] = CSRF
tip = lambda body: c.post('/api/tip', json=body, headers={'X-CSRF-Token': CSRF}, base_url=BASE)

r = tip({'recipient_user_id': bob, 'amount': 5, 'currency': 'USDC', 'request_id': 'a1', 'message': 'gg'})
j = r.get_json() or {}
check('a USDC tip goes through', r.status_code == 200 and j.get('ok') and j.get('currency') == 'USDC')
check('...as a Solana USDC transfer of the full amount to the recipient\'s trading wallet',
      sent and sent[-1][0] == 'spl' and sent[-1][2] == str(d.USDC_MINT) and sent[-1][3] == trading[bob_w]
      and sent[-1][4] == Decimal('5') and sent[-1][5] is False)
with sqlite3.connect(d.DB_FILE) as conn:
    row = conn.execute('SELECT currency, amount, recipient_user_id, tx_hash FROM tip_transactions ORDER BY id DESC').fetchone()
check('...recorded in the tip ledger as USDC', row and row[0] == 'USDC' and abs(row[1] - 5) < 1e-9 and row[2] == bob)

r = tip({'recipient_user_id': bob, 'amount': 0.01, 'currency': 'SOL', 'request_id': 'a2'})
check('a SOL tip still goes through as a native transfer', r.status_code == 200 and (r.get_json() or {}).get('currency') == 'SOL'
      and sent[-1][0] == 'sol' and sent[-1][2] == trading[bob_w])
check('any other currency is refused', tip({'recipient_user_id': bob, 'amount': 1, 'currency': 'BTC'}).status_code == 409)
check('a USDC tip under one cent is refused', tip({'recipient_user_id': bob, 'amount': 0.001, 'currency': 'USDC'}).status_code == 400)
check('you cannot tip yourself', tip({'recipient_user_id': alice, 'amount': 1, 'currency': 'USDC'}).status_code == 400)
n = len(sent)
check('the same USDC tip twice within 45 s is refused (no double send)',
      tip({'recipient_user_id': bob, 'amount': 5, 'currency': 'USDC'}).status_code == 409 and len(sent) == n)

with sqlite3.connect(d.DB_FILE) as conn:
    tip_id = conn.execute("SELECT id FROM tip_transactions WHERE currency='USDC'").fetchone()[0]
tip_experience._transition(d, tip_id, 'confirmed')
with sqlite3.connect(d.DB_FILE) as conn:
    note = conn.execute("SELECT content FROM notifications WHERE user_id=? AND type='tip' ORDER BY id DESC", (bob,)).fetchone()
check('the recipient\'s notification reads "5.00 USDC", not 5.000000000', note and '5.00 USDC' in note[0] and '5.000000000' not in note[0])
stats = c.get('/api/profile/%d/tip-stats' % bob, base_url=BASE).get_json()
check('profile tip totals count USDC separately', stats.get('received_usdc') == 5.0)

html = open(os.path.join(ROOT, 'templates', 'profile.html'), encoding='utf-8').read()
check('the tip sheet has a SOL | USDC switch with presets for each',
      'onclick="_tipSetCur(\'SOL\')"' in html and 'onclick="_tipSetCur(\'USDC\')"' in html
      and 'data-cur="USDC" data-v="{{ v }}"' in html and 'currency:_tipCur' in html and "currency:'SOL'" not in html)
js = open(os.path.join(ROOT, 'static', 'tip-experience.js'), encoding='utf-8').read()
check('...and the profile shows USDC tips next to SOL', "both(d.received_sol,d.received_usdc)" in js)
raise SystemExit(0 if all(checks) else 1)
