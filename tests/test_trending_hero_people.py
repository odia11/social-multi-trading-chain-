"""Public identities behind Trending Bullish, Bearish and Like counts.

Uses a temporary SQLite database; no production user or trading data is read.
"""
from pathlib import Path
import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['ORCAGENT_TRENDING_ALERTS'] = '0'
from flask import Flask
import trending_hero as th

MINT = 'WojakMint1111111111111111111111111111111pump'

with tempfile.TemporaryDirectory() as tmp:
    db = str(Path(tmp) / 'fake.db')
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, wallet_address TEXT, username TEXT, avatar_url TEXT, is_verified INTEGER, encrypted_private_key TEXT)')
    conn.executemany('INSERT INTO users VALUES (?,?,?,?,?,?)', [
        (1, 'FirstWallet111', 'First', '/avatar/default/first', 1, 'SECRET_NEVER_RETURN'),
        (2, 'SecondWallet22', 'Second', '', 0, 'SECRET_NEVER_RETURN'),
        (3, 'ThirdWallet333', 'Third', '', 0, 'SECRET_NEVER_RETURN'),
    ])
    conn.commit()
    conn.close()

    class D:
        app = Flask(__name__)
        DB_FILE = db
        rate_limit = staticmethod(lambda count, seconds: (lambda route: route))
        _authenticated_wallet = staticmethod(lambda: None)
        _feed_avatar_photo_url = staticmethod(lambda url, wallet, cache: url)

    d = D()
    th._state['recent'][MINT] = time.time()
    th.install(d)
    conn = sqlite3.connect(db)
    conn.execute('INSERT INTO trending_hero_votes (mint,user_id,vote) VALUES (?,?,?)', (MINT, 1, 1))
    conn.execute('INSERT INTO trending_hero_votes (mint,user_id,vote) VALUES (?,?,?)', (MINT, 2, 1))
    conn.execute('INSERT INTO trending_hero_votes (mint,user_id,vote) VALUES (?,?,?)', (MINT, 3, -1))
    conn.execute('INSERT INTO trending_hero_likes (mint,user_id) VALUES (?,?)', (MINT, 1))
    conn.execute('INSERT INTO trending_hero_likes (mint,user_id) VALUES (?,?)', (MINT, 3))
    conn.commit()
    conn.close()
    client = d.app.test_client()
    def people(kind, offset=0, mint=MINT):
        return client.get('/api/home/trending-hero/users', query_string={'kind': kind, 'mint': mint, 'offset': offset})

    bull = people('bull')
    assert bull.status_code == 200
    b = bull.get_json()
    assert b['count'] == 2 and {u['username'] for u in b['users']} == {'First', 'Second'}
    assert all('encrypted_private_key' not in u and 'user_id' not in u for u in b['users'])
    assert b['users'][0]['avatar_url'].startswith('/avatar/default/') or b['users'][1]['avatar_url'].startswith('/avatar/default/')
    assert b['next_offset'] is None
    bear = people('bear').get_json()
    assert bear['count'] == 1 and bear['users'][0]['username'] == 'Third'
    likes = people('like').get_json()
    assert likes['count'] == 2 and {u['username'] for u in likes['users']} == {'First', 'Third'}
    assert people('like', offset=1).get_json()['count'] == 2
    assert len(people('like', offset=1).get_json()['users']) == 1
    assert people('like', offset=-1).status_code == 400
    assert people('like', offset='bad').status_code == 400
    assert people('unknown').status_code == 400
    assert people('bull', mint='unrelated').status_code == 404
    assert people('bull', mint="' OR 1=1 --").status_code == 404

    # Updating votes must update public lists without duplicating a user.
    conn = sqlite3.connect(db)
    conn.execute('INSERT OR REPLACE INTO trending_hero_votes (mint,user_id,vote) VALUES (?,?,?)', (MINT, 1, -1))
    conn.commit()
    conn.close()
    assert people('bull').get_json()['count'] == 1
    assert people('bear').get_json()['count'] == 2
    assert people('like').get_json()['count'] == 2

    # A popular card can have more than one page of actual users.
    conn = sqlite3.connect(db)
    conn.executemany('INSERT INTO users VALUES (?,?,?,?,?,?)', [
        (i, f'Wallet{i}', f'User{i}', '', 0, 'SECRET_NEVER_RETURN')
        for i in range(4, 111)
    ])
    conn.executemany('INSERT INTO trending_hero_likes (mint,user_id) VALUES (?,?)',
                     [(MINT, i) for i in range(4, 111)])
    conn.commit()
    conn.close()
    first = people('like').get_json()
    second = people('like', offset=100).get_json()
    assert first['count'] == 109 and len(first['users']) == 100 and first['next_offset'] == 100
    assert second['count'] == 109 and len(second['users']) == 9 and second['next_offset'] is None
    assert not ({u['wallet'] for u in first['users']} & {u['wallet'] for u in second['users']})

print('PASS Bullish, Bearish and Like lists show real joined user accounts')
print('PASS votes switching updates lists, and likes are independent')
print('PASS stable profile wallet/avatar fields without trading secrets')
print('PASS real two-page pagination and input validation, including SQL-injection-shaped input')
