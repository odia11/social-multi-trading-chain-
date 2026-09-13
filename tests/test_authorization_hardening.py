"""Static regression checks for the privileged-route authorization guard."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = (ROOT / 'authorization_hardening.py').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')

checks = []

def check(name, cond):
    checks.append((name, bool(cond)))

check('admin API is protected by outer middleware',
      "path == '/api/admin'" in AUTH and "path.startswith('/api/admin/')" in AUTH)
check('admin page is protected too',
      "path == '/admin'" in AUTH and "path.startswith('/admin/')" in AUTH)
check('bridge test/admin utility is protected', "path == '/bridge-test'" in AUTH)
check('guard uses authenticated wallet proof rather than a raw session wallet',
      "_authenticated_wallet" in AUTH)
check('non-privileged roles fail closed',
      "_ADMIN_ROLES" in AUTH and "return 'user'" in AUTH)
check('role query is parameterized',
      "WHERE wallet_address=?" in AUTH and "(wallet,)" in AUTH)
check('owner wallets are explicitly supported', "OWNER_WALLET" in AUTH)
check('API returns 401 for anonymous access', "'Authentication required'}), 401" in AUTH)
check('API returns 403 for wrong role', "'Forbidden'}), 403" in AUTH)
check('authorization layer is installed in production entrypoint',
      '_install_authorization_hardening(_dashboard)' in ENTRY)

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(('PASS' if ok else 'FAIL') + ': ' + name)
if failed:
    raise SystemExit('authorization hardening regression failure: ' + ', '.join(failed))
