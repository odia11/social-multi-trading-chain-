"""Admin Console navigation is visible only to real privileged staff roles."""
import os, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update({
    'DATA_DIR': tempfile.mkdtemp(),
    'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
    'ORCAGENT_FRONTS_GAS': '0',
})
import app_entry  # noqa: E402
from solders.keypair import Keypair  # noqa: E402

d = app_entry._dashboard
app = app_entry.app
wallet = str(Keypair().pubkey())
uid = d.get_or_create_user(wallet)

def set_role(role):
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('UPDATE users SET role=? WHERE id=?', (role, uid))

def api_me():
    c = app.test_client()
    with c.session_transaction(base_url='https://orcagent.fun') as s:
        s['wallet'] = wallet
        s['user_id'] = uid
    return c.get('/api/me', base_url='https://orcagent.fun').get_json()

set_role('verified')
assert d.get_user_role(wallet) == 'user'
me = api_me()
assert me['role'] == 'user' and me['can_access_admin'] is False and me['is_admin'] is False

set_role('analyst')
assert d.get_user_role(wallet) == 'analyst'
me = api_me()
assert me['role'] == 'analyst' and me['can_access_admin'] is True

set_role('moderator')
assert d.get_user_role(wallet) == 'moderator' and api_me()['can_access_admin'] is True

nav = (ROOT / 'dashboard.py').read_text(encoding='utf-8')
navbar_js = (ROOT / 'static' / 'navbar.js').read_text(encoding='utf-8')
mobile_js = (ROOT / 'static' / 'mobile-bottom-nav.js').read_text(encoding='utf-8')
assert 'hidden aria-hidden="true"' in nav
assert 'd.can_access_admin===true' in navbar_js
assert "src.hidden||src.getAttribute('aria-hidden')==='true'||src.style.display==='none'" in mobile_js
assert "orca:admin-access-changed" in mobile_js
print('PASS normal users cannot expose Admin Console; privileged staff can')
