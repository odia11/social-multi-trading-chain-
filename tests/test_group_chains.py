"""A group can be about a token on any chain the platform trades.

WHAT WAS HAPPENING
Groups were Solana-only, and nothing said so out loud -- the create form
just labelled its one required field "Solana mint address". So a group for a
BNB Chain, Base, Arbitrum, Polygon or Robinhood Chain token could not be
made at all, on a platform that trades all six.

WHAT THIS NEEDED
A token address means nothing on its own: every EVM chain shares one address
format, so 0x… is equally well-formed on BNB Chain and on Base. Without
knowing which chain it is meant to be, "verify this group is really about
that token" -- the whole stated purpose of the field -- cannot be done. So
the chain is stored alongside the address, and validation is per chain.

The chain the caller sends is checked against the server's own list before
it is used to pick an address format. A made-up chain would otherwise be a
way to store an address that nothing can ever verify.

WHAT THIS MUST NOT BREAK
Groups that already exist. Every row that predates the column really is a
Solana group, because that is all that could be created, so the column
default states a fact about those rows rather than guessing at one -- and
the migration is checked here against a database built with the OLD schema,
which is what a deploy actually meets.

The chain list is derived from EVM_CHAINS rather than typed out again, so a
chain added there appears in the group form too. This codebase has twice
been bitten by a second copy of a chain/rule list drifting out of step, so
that is asserted here rather than left to hold by luck.
"""
import os
import re
import sqlite3
import sys
import tempfile

REPO = '/home/user/Orc-agent-Solana-chain-'
sys.path.insert(0, REPO)

_DATA = tempfile.mkdtemp()
os.environ.update({
    'DATA_DIR': _DATA,
    'SECRET_KEY': 'x' * 32,
    'ENCRYPTION_KEY': 'KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK=',
    'DEV': '1',
})
import dashboard as m  # noqa: E402

checks = []


def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


WALLET = 'Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'
SOL_ADDR = 'DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263'
EVM_ADDR = '0x2170Ed0880ac9A755fd29B2688956BD959F933F8'
CSRF = 'tok' * 10

client = m.app.test_client()
with client.session_transaction() as s:
    s['wallet'] = WALLET
    s['user_id'] = m.get_or_create_user(WALLET)
    s['csrf_token'] = CSRF


def create(chain, address, name='group'):
    r = client.post('/api/groups',
                    json={'name': name, 'token_symbol': 'TKN',
                          'token_address': address, 'chain': chain},
                    headers={'X-CSRF-Token': CSRF})
    return r.status_code, r.get_json()


# ── 1. the offered chains are the platform's own, not a second list ───────
check('the group chain list is every EVM chain the platform trades, plus '
      'Solana -- derived from EVM_CHAINS, not typed out again',
      set(m.TOKEN_CHAINS) == {'solana'} | set(m.EVM_CHAINS.keys()))
check('...with Solana first, so the default selection is the one most '
      'groups will want',
      m.TOKEN_CHAINS[0] == 'solana')

src = open(REPO + '/dashboard.py', encoding='utf-8').read()
decl = re.search(r'^TOKEN_CHAINS\s*=\s*(.+)$', src, re.M)
check('TOKEN_CHAINS is built from EVM_CHAINS in the source, so a chain added '
      'there cannot go missing from the group form',
      decl is not None and 'EVM_CHAINS' in decl.group(1))

# ── 2. every chain can actually have a group ─────────────────────────────
created = {}
for chain in m.TOKEN_CHAINS:
    addr = SOL_ADDR if chain == 'solana' else EVM_ADDR
    status, body = create(chain, addr, chain + ' group')
    ok = status == 200 and body.get('ok')
    if ok:
        created[chain] = body['group_id']
    check(f'a group can be created on {m.chain_display_name(chain)}', ok)

# ── 3. an address is only accepted for a chain it could belong to ────────
for chain, addr, label in [
    ('bsc', SOL_ADDR, 'a Solana address offered as a BNB Chain token'),
    ('solana', EVM_ADDR, 'an EVM address offered as a Solana token'),
    ('bsc', '0x123', 'a truncated EVM address'),
    ('base', 'not-an-address', 'plain nonsense'),
    ('solana', '', 'no address at all'),
]:
    status, body = create(chain, addr)
    check(f'refused: {label}', status == 400 and not body.get('ok'))

status, body = create('ethereum', EVM_ADDR)
check('refused: a chain the platform does not trade -- the chain decides '
      'which address format is accepted, so it is checked against the '
      "server's own list rather than trusted from the form",
      status == 400 and not body.get('ok'))

# ── 4. the chain travels back out with the group ─────────────────────────
detail = client.get('/api/groups/%d' % created['base']).get_json()['group']
check('the group detail API reports the chain, so a member can tell which '
      "token they are verifying", detail.get('chain') == 'base')
check('...with a readable label rather than only an internal id',
      detail.get('chain_label') == 'Base')

mine = client.get('/api/groups/mine').get_json()['groups']
check('the "my groups" list carries the chain too',
      mine and all(g.get('chain') for g in mine))

# ── 5. the form offers all of them ───────────────────────────────────────
html = client.get('/groups').get_data(as_text=True)
for chain in m.TOKEN_CHAINS:
    check(f'the create-group form offers {m.chain_display_name(chain)}',
          f'value="{chain}"' in html)
check('each chain carries its own address hint, so the field stops telling '
      'everyone to paste a Solana mint address',
      'data-placeholder="Solana mint address"' in html
      and html.count('data-placeholder="0x') == len(m.TOKEN_CHAINS) - 1)

# ── 6. the migration, against a database built with the OLD schema ───────
old_dir = tempfile.mkdtemp()
old_db = os.path.join(old_dir, 'orcagent.db')
con = sqlite3.connect(old_db)
con.execute('''CREATE TABLE groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT, token_address TEXT,
    token_symbol TEXT NOT NULL, name TEXT NOT NULL, description TEXT,
    is_private INTEGER DEFAULT 0, created_by INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
con.execute("INSERT INTO groups (token_address, token_symbol, name, created_by) "
            "VALUES (?, 'WIF', 'WIF Whales', 1)", (SOL_ADDR,))
con.commit()
con.close()

_real_db = m.DB_FILE
try:
    m.DB_FILE = old_db
    m.init_db()
    m.run_migrations()
    con = sqlite3.connect(old_db)
    cols = [r[1] for r in con.execute('PRAGMA table_info(groups)')]
    # by name: init_db() seeds its own official group, so "the first row"
    # is not necessarily the one this test put there.
    row = con.execute("SELECT name, chain FROM groups WHERE name='WIF Whales'").fetchone()
    con.close()
finally:
    m.DB_FILE = _real_db

check('a database created before this change gains the chain column instead '
      'of erroring on the next start', 'chain' in cols)
check('...and the group already in it survives',
      row is not None and row[0] == 'WIF Whales')
check('...marked solana, which is what it actually is -- Solana was the only '
      'thing a group could be about until now, so this states a fact rather '
      'than guessing',
      row is not None and row[1] == 'solana')

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
