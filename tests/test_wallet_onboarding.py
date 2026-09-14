"""Regression checks for Phantom-style guest wallet onboarding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
py = (ROOT / 'wallet_onboarding.py').read_text(encoding='utf-8')
js = (ROOT / 'static' / 'wallet-onboarding.js').read_text(encoding='utf-8')
entry = (ROOT / 'app_entry.py').read_text(encoding='utf-8')
privacy = (ROOT / 'response_privacy_hardening.py').read_text(encoding='utf-8')

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

check('wallet onboarding is installed in production',
      'from wallet_onboarding import install as _install_wallet_onboarding' in entry
      and '_install_wallet_onboarding(_dashboard)' in entry)
check('guest flow exposes create, import and Phantom choices',
      'Create New Wallet' in js and 'Import Existing Wallet' in js and 'Connect Phantom' in js)
check('every guest connect control opens the onboarding chooser',
      '#oa-guest-connect-btn' in js and '#guest-banner .gb-link' in js
      and 'OrcAgentWalletOnboarding={open:open}' in js)
check('new wallet creation returns fresh Solana and EVM keys',
      'sol = Keypair()' in py and 'evm = Account.create()' in py
      and "'solana_private_key': sol_private" in py
      and "'evm_private_key': evm_private" in py)
check('new wallet cannot activate until backup is confirmed',
      "body.get('backup_confirmed') is not True" in py
      and 'I saved both private keys safely.' in js)
check('confirmed wallet becomes a persistent authenticated session',
      "session['wallet'] = sol_address" in py and 'session.permanent = True' in py
      and '_issue_device_token' in py and '_set_device_cookie' in py)
check('wallet secrets are encrypted before database storage',
      'encrypt(sol_private, sol_address)' in py and 'encrypt(evm_private, sol_address)' in py
      and 'encrypted_private_key_bsc' in py)
check('import supports existing Solana private key and optional EVM key',
      "solana_private_key" in js and "evm_private_key" in js
      and "_IMPORT = '/api/onboarding/wallet/import'" in py)
check('generated EVM key during import is staged until backup confirmation',
      "'needs_confirmation': True" in py
      and 'Save your new EVM private key' in js)
check('one-time secret responses are explicitly privacy-guarded',
      '/api/onboarding/wallet/create' in privacy
      and '/api/onboarding/wallet/import' in privacy
      and '_valid_one_time_key_export' in privacy)
check('onboarding API responses are no-store',
      "Cache-Control'] = 'no-store, no-cache, must-revalidate, private'" in py)

raise SystemExit(0 if all(checks) else 1)
