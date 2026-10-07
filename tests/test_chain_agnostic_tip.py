"""Current Solana tip contract: SOL or USDC."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = (ROOT / 'portfolio_token_withdraw.py').read_text()
PROFILE = (ROOT / 'templates' / 'profile.html').read_text()
LEDGER = (ROOT / 'tip_experience.py').read_text()

checks = []
def check(label, condition):
    checks.append(bool(condition))
    print(('PASS ' if condition else 'FAIL ') + label)

tip = BACKEND[BACKEND.index("@app.post('/api/tip')"):
              BACKEND.index("@app.post('/api/wallet/send-token')")]

check('profile sends immutable recipient id, not a wallet address',
      "fetch('/api/tip'" in PROFILE
      and 'recipient_user_id:_tipPeerId' in PROFILE
      and '_tipRecipient' not in PROFILE)
check('server resolves the recipient wallet itself',
      '_user_tip_wallets(d, recipient_user_id)' in tip
      and "body.get('to_address')" not in tip)
check('recipient resolver is Solana-only',
      "SELECT wallet_address FROM users WHERE id=?" in BACKEND
      and "return {'session': session_wallet, 'solana': solana_wallet}" in BACKEND)
check('tips transfer real Solana USDC',
      "_solana_transfer(" in tip and 'd.USDC_MINT' in tip)
# SOL or USDC since #214. A USDC tip arrives in full: the sender's own SOL
# pays the network fee; no USDC is swapped into SOL behind their back
# (that bootstrap belonged to the USDC-only design and is not used).
check('a USDC tip sends the full amount and never sells USDC for gas',
      "str(d.USDC_MINT), recipient_address, amount," in tip
      and 'allow_user_funded_gas=False' in tip and '_gasless_solana_native_topup' not in tip)
check('only SOL or USDC', "if currency not in ('SOL', 'USDC'):" in tip)
check('duplicate submissions are guarded independent of RPC, per currency',
      "key = ('tip', sender_wallet, recipient_user_id, currency, str(amount.normalize()))" in tip
      and "_RECENT.get(key, 0) < 45" in tip)
check('tip mutation is authenticated, CSRF checked and rate limited',
      'd._authenticated_wallet()' in tip
      and '_csrf_ok(d)' in tip
      and "_rate_ok('tip_wallet:' + sender_wallet" in tip)
check('successful submission is persisted before notification workflow',
      '_record_tip(' in tip and "status':'submitted'" in tip
      and 'record_submitted' in BACKEND)
check('ledger only counts a confirmed tip as delivered',
      "state == 'confirmed'" in LEDGER
      and 'tip_transactions' in LEDGER)
check('tip response exposes the Solana explorer receipt',
      "'explorer':_explorer(chain, tx_hash)" in tip)

raise SystemExit(0 if all(checks) else 1)
