"""Regression checks for browser-local guest wallet onboarding."""
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
check('new wallet keys are generated in the browser',
      'nacl.sign.keyPair()' in js and 'freshEvmKey()' in js
      and "mode': 'client-generated'" in py)
check('server never exports guest onboarding private keys',
      '_sealed_response' not in py
      and '/api/onboarding/wallet/create' not in privacy
      and '_IMPORT_KEY_EXPORT_PATH' not in privacy)
check('private keys travel only inside an encrypted request envelope',
      'securePost(' in js and "alg:'A256GCM'" in js
      and '_open_client_envelope(envelope)' in py
      and 'AESGCM(key).decrypt' in py)
check('new wallet cannot activate until backup is confirmed',
      "body.get('backup_confirmed') is not True" in py
      and 'I saved both private keys safely.' in js)
check('confirmed wallet becomes a persistent authenticated session',
      "session['wallet'] = sol_address" in py and 'session.permanent = True' in py
      and '_issue_device_token' in py and '_set_device_cookie' in py)
check('wallet secrets are encrypted before database storage',
      'encrypt(sol_private, sol_address)' in py and 'encrypt(evm_private, sol_address)' in py
      and 'encrypted_private_key_bsc' in py)
check('import creates a browser-local EVM key when omitted',
      'OrcAgent created this key securely on your device.' in js
      and "EVM private key is required" in py)
check('onboarding assets are cache-busted',
      'wallet-onboarding.js?v=4' in py and 'wallet-onboarding.css?v=4' in py)

check('backup UI masks keys and exposes explicit show/copy controls',
      'type="password"' in js and 'data-show=' in js and 'data-copy=' in js
      and 'navigator.clipboard.writeText' in js)
check('professional backup flow includes progress and security context',
      'oa-ob-progress' in js and 'Secure your wallet' in js
      and 'Encrypted during activation' in js)

raise SystemExit(0 if all(checks) else 1)
