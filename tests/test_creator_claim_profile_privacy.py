"""Private creator-fee receipts on a user's own profile only."""
import ast
import datetime
import re
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SRC=(ROOT/'dashboard.py').read_text()
HTML=(ROOT/'templates'/'profile.html').read_text()
TREE=ast.parse(SRC)

def source_fn(name):
    node=next(n for n in ast.walk(TREE) if isinstance(n,ast.FunctionDef) and n.name==name)
    return ast.get_source_segment(SRC,node) or ''

ns={'sqlite3':sqlite3,'datetime':datetime,'re':re,'_time_ago_str':lambda _: 'now'}
exec(source_fn('_recent_creator_claims_for_profile'),ns)
recent=ns['_recent_creator_claims_for_profile']

conn=sqlite3.connect(':memory:')
conn.row_factory=sqlite3.Row
conn.executescript('''
CREATE TABLE token_launches(id TEXT PRIMARY KEY,wallet TEXT,symbol TEXT);
CREATE TABLE token_reward_claims(
 id TEXT PRIMARY KEY,launch_id TEXT,wallet TEXT,quote_asset TEXT,status TEXT,
 received_raw TEXT,signature TEXT,created_at INTEGER,confirmed_at INTEGER
);
''')
wa='WalletA';wb='WalletB';sig_a='1'*88;sig_b='2'*88
conn.execute('INSERT INTO token_launches VALUES (?,?,?)',('a',wa,'AAA'))
conn.execute('INSERT INTO token_launches VALUES (?,?,?)',('b',wb,'BBB'))
conn.executemany('INSERT INTO token_reward_claims VALUES (?,?,?,?,?,?,?,?,?)',[
 ('ca','a',wa,'USDC','confirmed','1250000',sig_a,100,200),
 ('cb','b',wb,'USDC','confirmed','999999999',sig_b,100,200),
 ('cp','a',wa,'USDC','prepared','777000000','',300,0),
])
rows=recent(conn,wa,10)
assert len(rows)==1,rows
assert rows[0]['symbol']=='AAA' and rows[0]['amount']=='1.25 USDC'
assert rows[0]['signature']==sig_a
assert all(r['symbol']!='BBB' for r in rows)
assert '777' not in repr(rows),'prepared accrued amount must never appear as received'

profile_src=source_fn('profile')
profile_view_src=source_fn('profile_view')
assert '_recent_creator_claims_for_profile(conn, wallet)' in profile_src
assert '_recent_creator_claims_for_profile(conn, wallet_address) if is_own else []' in profile_view_src
assert HTML.count('{% if is_own_profile %}')>=2
assert 'id="pf-panel-claims"' in HTML and ">Claims</button>" in HTML
assert 'https://solscan.io/tx/{{ c.signature }}' in HTML
print('PASS own-profile creator claim receipts are private, signed and based only on verified received amounts')
