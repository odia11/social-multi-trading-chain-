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
check('constant ADMIN_WALLET super-admin is included in owner boundary',
      "getattr(dashboard_module, 'ADMIN_WALLET'" in AUTH and 'owners.add(admin_wallet)' in AUTH)
check('dashboard OWNER_WALLETS set is included in owner boundary',
      "getattr(dashboard_module, 'OWNER_WALLETS'" in AUTH and 'owners.update' in AUTH)
check('API returns 401 for anonymous access',
      "_deny(401, 'Authentication required')" in AUTH)
check('API returns 403 for wrong role',
      "_deny(403, 'Forbidden')" in AUTH)

check('staff invite is owner-only',
      "'/api/admin/invite'" in AUTH and '_OWNER_ONLY_ADMIN_PATHS' in AUTH)
check('role changes are owner-only',
      "'/api/admin/role/change'" in AUTH and "'/api/admin/role/remove'" in AUTH)
check('platform feature mutation is owner-only',
      "'/api/admin/features/toggle'" in AUTH and '_OWNER_ONLY_ADMIN_PATHS' in AUTH)
check('analyst role is server-side read-only',
      "role == 'analyst'" in AUTH and "'Read-only admin role'" in AUTH)
check('moderator mutations are allowlisted, not broadly trusted',
      '_MODERATOR_ADMIN_MUTATION_PREFIXES' in AUTH
      and "role == 'moderator'" in AUTH
      and "not path.startswith(_MODERATOR_ADMIN_MUTATION_PREFIXES)" in AUTH)
check('moderator allowlist contains support and moderation actions',
      "'/api/admin/ban'" in AUTH
      and "'/api/admin/post/delete'" in AUTH
      and "'/api/admin/user/verify'" in AUTH
      and "'/api/admin/support/threads/'" in AUTH)
check('admin mutations are checked before handler execution',
      "path.startswith('/api/admin') and method in _MUTATING" in AUTH
      and '_admin_mutation_denial(dashboard_module, path, role, wallet)' in AUTH)

check('authorization layer is installed in production entrypoint',
      '_install_authorization_hardening(_dashboard)' in ENTRY)

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(('PASS' if ok else 'FAIL') + ': ' + name)
if failed:
    raise SystemExit('authorization hardening regression failure: ' + ', '.join(failed))
