"""An owner can see and remove the moderators they made; a badge opens its page.

Before: listing the team, changing or removing a role and the feature switches
accepted one built-in wallet only. An owner signed in with their own owner
wallet got 403, so Settings said "No members yet" right after they made
someone a moderator -- and that moderator could not be removed. On a phone,
the Trading tab with "9+" opened its first page (Positions at risk) even when
the waiting items were in AI filters; People opened Users, not Support.
"""
import json, os, re, sqlite3, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_TRENDING_ALERTS': '0', 'ORCAGENT_PLATFORM_POSTS': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
app = app_entry.app
from solders.keypair import Keypair  # noqa: E402
ROOT = os.path.join(os.path.dirname(__file__), '..')

checks = []
def check(name, cond, detail=''):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name + ((' -- %s' % detail) if detail and not cond else ''), flush=True)

OWNER = sorted(w for w in d.OWNER_WALLETS if w != d.ADMIN_WALLET)[0]   # an owner that is not the built-in admin wallet
d.get_or_create_user(OWNER)
mod = str(Keypair().pubkey()); d.get_or_create_user(mod)
legacy = str(Keypair().pubkey()); d.get_or_create_user(legacy)
invited = str(Keypair().pubkey())
c = sqlite3.connect(d.DB_FILE)
c.execute("INSERT INTO admin_roles(wallet_address, role, invited_by) VALUES (?, 'Moderator', ?)", (mod, OWNER))
c.execute("UPDATE users SET role='moderator' WHERE wallet_address IN (?, ?)", (mod, legacy))
inv_id = c.execute("INSERT INTO admin_invites(wallet, role, invited_by) VALUES (?, 'Moderator', ?)", (invited, OWNER)).lastrowid
c.commit(); c.close()

BASE = 'https://orcagent.fun'
def client(wallet):
    cl = app.test_client()
    with cl.session_transaction(base_url=BASE) as s:
        s['wallet'] = wallet; s['csrf_token'] = 'tok' * 10
    return cl
def post(cl, path, body):
    return cl.post(path, json=body, headers={'X-CSRF-Token': 'tok' * 10}, base_url=BASE)

owner = client(OWNER)
r = owner.get('/api/admin/roles', base_url=BASE)
data = r.get_json() or {}
members = {m['wallet']: m['role'] for m in data.get('members', [])}
check('an owner signed in with their own owner wallet sees the team (was 403 -> "No members yet")',
      r.status_code == 200 and data.get('ok'), str(r.status_code))
check('...the moderator they made is listed', members.get(mod) == 'Moderator', str(members))
check('...and a moderator kept only in users.role too, so it can be removed', members.get(legacy) == 'Moderator', str(members))
check('...owners are listed first, as Super-admin', data['members'][0]['role'] == 'Super-admin'
      and members.get(OWNER) == 'Super-admin' and members.get(d.ADMIN_WALLET) == 'Super-admin')

r = post(owner, '/api/admin/role/remove', {'wallet': mod})
check('the owner can remove the moderator', r.status_code == 200 and r.get_json().get('ok') and d.get_user_role(mod) == 'user',
      str(r.get_json()))
check('...and it is gone from the list', mod not in {m['wallet'] for m in owner.get('/api/admin/roles', base_url=BASE).get_json()['members']})
r = post(owner, '/api/admin/role/change', {'wallet': legacy, 'role': 'Analyst'})
check('a users.role-only moderator can be changed', r.status_code == 200 and d.get_user_role(legacy) == 'analyst', str(r.get_json()))
r = post(owner, '/api/admin/role/remove', {'wallet': legacy})
check('...and removed', r.status_code == 200 and d.get_user_role(legacy) == 'user')
check('an owner cannot be removed', post(owner, '/api/admin/role/remove', {'wallet': d.ADMIN_WALLET}).status_code == 400)

r = post(owner, '/api/admin/invite/cancel', {'id': inv_id})
pending = owner.get('/api/admin/invites', base_url=BASE).get_json().get('invites', [])
check('a pending invite can be cancelled', r.status_code == 200 and not any(i['id'] == inv_id for i in pending), str(r.get_json()))

# Someone with a role, but not an owner, still cannot manage the team.
other = str(Keypair().pubkey()); d.get_or_create_user(other)
c = sqlite3.connect(d.DB_FILE)
c.execute("INSERT INTO admin_roles(wallet_address, role) VALUES (?, 'Moderator')", (other,)); c.commit(); c.close()
m = client(other)
check('a moderator cannot list, remove or cancel', m.get('/api/admin/roles', base_url=BASE).status_code == 403
      and post(m, '/api/admin/role/remove', {'wallet': OWNER}).status_code == 403
      and post(m, '/api/admin/invite/cancel', {'id': inv_id}).status_code == 403)

# ── a tab with a badge opens the page the badge comes from ──
html = open(os.path.join(ROOT, 'templates', 'admin.html'), encoding='utf-8').read()
fn = re.search(r'function showGroup\(g\) \{.*?\n\}', html, re.S).group(0)
groups = re.search(r'var _GROUPS = (\{.*?\});', html, re.S).group(1)
js = 'var _GROUPS=' + groups + ';var _ROLE_TABS={admin:["overview","users","moderation","support","revenue","trades","risk","performance","aifilters","security","system","settings"]};var _userRole="admin";var _badgeCounts={};var shown=[];function showView(v){shown.push(v)}\n' + fn + '''
showGroup("trading"); _badgeCounts={aifilters:12}; showGroup("trading"); _badgeCounts={support:2}; showGroup("people");
_badgeCounts={risk:1,aifilters:3}; showGroup("trading");
console.log(JSON.stringify(shown));'''
out = subprocess.run(['node', '-e', js], capture_output=True, text=True, timeout=30)
shown = json.loads(out.stdout.strip() or '[]')
check('Trading without a badge opens its first page', shown[:1] == ['risk'], str(shown) + out.stderr[-300:])
check('Trading 9+ opens AI filters when that is where the items wait', shown[1:2] == ['aifilters'], str(shown))
check('People with unread support opens Support', shown[2:3] == ['support'], str(shown))
check('...and with several, the first page that has one', shown[3:4] == ['risk'], str(shown))

print('%d/%d' % (sum(checks), len(checks)))
sys.exit(0 if all(checks) else 1)
