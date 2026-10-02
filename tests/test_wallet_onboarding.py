"""Regression checks for Solana-only browser-local guest wallet onboarding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
py = (ROOT / 'wallet_onboarding.py').read_text()
js = (ROOT / 'static' / 'wallet-onboarding.js').read_text()
entry = (ROOT / 'app_entry.py').read_text()
privacy = (ROOT / 'response_privacy_hardening.py').read_text()

checks=[]
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name)

low=js.lower()
check('wallet onboarding is installed in production',
      'from wallet_onboarding import install as _install_wallet_onboarding' in entry
      and '_install_wallet_onboarding(_dashboard)' in entry)
check('guest flow exposes create, import and Phantom choices',
      'create new wallet' in low and 'import existing wallet' in low and 'phantom' in low)
check('new wallet key is generated in browser on Solana only',
      'nacl.sign.keyPair()' in js and 'freshEvmKey' not in js and 'evm_private_key' not in js
      and "mode': 'client-generated'" in py)
check('server onboarding has no EVM-key path',
      'evm_private_key' not in py and '_derive_evm' not in py and 'eth_account' not in py)
check('private key travels only inside encrypted request envelope',
      'securePost(' in js and "alg:'A256GCM'" in js
      and '_open_client_envelope(envelope)' in py and 'AESGCM(key).decrypt' in py)
check('activation requires Solana-key backup confirmation',
      "body.get('backup_confirmed') is not True" in py
      and 'i saved my solana private key securely' in low
      and 'disabled=!c.checked' in js.replace(' ',''))
check('confirmed wallet becomes persistent authenticated session',
      "session['wallet'] = sol_address" in py and 'session.permanent = True' in py
      and '_issue_device_token' in py and '_set_device_cookie' in py)
check('only Solana secret is encrypted/stored',
      'encrypt(sol_private, sol_address)' in py
      and 'encrypt(evm_private' not in py
      and 'encrypted_private_key_bsc' not in py)
check('import requires only the existing Solana key',
      'enter your existing solana private key' in low
      and 'oa-import-evm' not in js and 'evm private key' not in low)
check('onboarding JS is cache-busted to current Solana-only version',
      'wallet-onboarding.js?v=7' in py)
check('backup UI masks key and provides explicit show/copy controls',
      'type="password"' in js and 'data-show=' in js and 'data-copy=' in js
      and 'navigator.clipboard.writeText' in js)
check('privacy guard does not need a guest key-export exception',
      '/api/onboarding/wallet/create' not in privacy)
check('chooser retains create/import/Phantom options',
      'oa-ob-option-featured' in js and 'RECOMMENDED' in js
      and 'Self-custodial' in js and 'Keys are never exposed' in js)

raise SystemExit(0 if all(checks) else 1)
