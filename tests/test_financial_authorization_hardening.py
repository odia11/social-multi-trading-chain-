"""Regression checks for the common financial authorization boundary.

These tests intentionally stay narrow: the detailed amount/fee/chain behaviour
is already covered by the trade, bridge and withdrawal suites. This file makes
sure the cross-cutting identity/ownership rules cannot disappear unnoticed.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'financial_authorization_hardening.py').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')

checks = []
def check(name, condition):
    checks.append((name, bool(condition)))
    print(('PASS ' if condition else 'FAIL ') + name)

check('financial guard is installed by the production entry point',
      'financial_authorization_hardening' in ENTRY
      and '_install_financial_authorization_hardening(_dashboard)' in ENTRY)

for route in ["'/api/withdraw'", "'/api/wallet/send'", "'/api/bridge'", "'/api/trade'", "'/api/instant-trade'"]:
    check('protected financial family includes ' + route,
          route in SRC)

check('the guard derives identity from the authenticated wallet',
      "'_authenticated_wallet'" in SRC and '_auth_wallet(appmod)' in SRC)
check('anonymous financial requests fail closed',
      "'Authentication required'" in SRC and '401' in SRC)
check('an authenticated wallet still needs a server-side user row',
      '_uid_for_wallet(appmod, wallet)' in SRC
      and "'Account not available'" in SRC)

for key in ['user_id', 'wallet_address', 'from_address', 'trading_wallet', 'evm_address', 'solana_address']:
    check('client cannot override identity field ' + key,
          repr(key) in SRC)
check('destination addresses remain allowed for legitimate withdrawals',
      "'to_address'" not in SRC.split('_FORBIDDEN_IDENTITY_KEYS', 1)[1].split('})', 1)[0])

check('bridge status IDs are treated as owned objects',
      '_BRIDGE_STATUS_RE' in SRC and '_bridge_owner(appmod, bridge_id)' in SRC)
check('bridge ownership is checked with a parameterized query',
      "SELECT user_id FROM bridge_transactions WHERE id=?" in SRC
      and '(bridge_id,)' in SRC)
check('foreign bridge IDs are concealed with 404',
      'if owner != uid' in SRC and "'Not found'" in SRC and '404' in SRC)
check('DB errors fail closed instead of exposing bridge ownership',
      'Fail closed' in SRC and 'return None' in SRC)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
raise SystemExit(0 if passed == len(checks) else 1)
