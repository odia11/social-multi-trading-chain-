"""Regression checks for OrcAgent object-level authorization hardening."""
import os
import sqlite3
import tempfile

import authorization_hardening as a


class Dummy:
    DB_FILE = ''


def build_db():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    con = sqlite3.connect(path)
    con.executescript('''
      CREATE TABLE users(id INTEGER PRIMARY KEY, wallet_address TEXT, role TEXT);
      CREATE TABLE messages(id INTEGER PRIMARY KEY, sender_id INTEGER, receiver_id INTEGER, message TEXT);
      CREATE TABLE notifications(id INTEGER PRIMARY KEY, user_id INTEGER, body TEXT);
      CREATE TABLE posts(id INTEGER PRIMARY KEY, user_id INTEGER, body TEXT);
      CREATE TABLE groups(id INTEGER PRIMARY KEY, created_by INTEGER, name TEXT);
      CREATE TABLE group_members(id INTEGER PRIMARY KEY, group_id INTEGER, user_id INTEGER, role TEXT);
      CREATE TABLE group_posts(id INTEGER PRIMARY KEY, group_id INTEGER, user_id INTEGER, body TEXT);
    ''')
    con.execute("INSERT INTO users VALUES(1,'WALLET1','user')")
    con.execute("INSERT INTO users VALUES(2,'WALLET2','user')")
    con.execute("INSERT INTO messages VALUES(10,1,2,'mine')")
    con.execute("INSERT INTO messages VALUES(11,2,1,'theirs')")
    con.execute("INSERT INTO notifications VALUES(20,1,'mine')")
    con.execute("INSERT INTO notifications VALUES(21,2,'theirs')")
    con.execute("INSERT INTO posts VALUES(30,1,'mine')")
    con.execute("INSERT INTO posts VALUES(31,2,'theirs')")
    con.execute("INSERT INTO groups VALUES(40,1,'mine')")
    con.execute("INSERT INTO groups VALUES(41,2,'theirs')")
    con.execute("INSERT INTO group_members VALUES(1,41,1,'member')")
    con.execute("INSERT INTO group_posts VALUES(50,41,1,'mine in other group')")
    con.execute("INSERT INTO group_posts VALUES(51,41,2,'theirs in other group')")
    con.commit(); con.close()
    return path


def check(name, ok):
    print(('PASS ' if ok else 'FAIL ') + name)
    return bool(ok)


path = build_db(); Dummy.DB_FILE = path
con = sqlite3.connect(path); con.row_factory = sqlite3.Row
checks = []
try:
    checks.append(check('own message is editable/deletable', a._message_owned(con, 10, 1, 'WALLET1') is True))
    checks.append(check('other user message is blocked', a._message_owned(con, 11, 1, 'WALLET1') is False))
    checks.append(check('own notifications batch is allowed', a._notification_ids_owned(con, [20], 1, 'WALLET1') is True))
    checks.append(check('mixed notification batch is blocked', a._notification_ids_owned(con, [20,21], 1, 'WALLET1') is False))
    checks.append(check('own post is owned', a._row_owned_by(con, 'posts', 30, 1, 'WALLET1') is True))
    checks.append(check('other post is not owned', a._row_owned_by(con, 'posts', 31, 1, 'WALLET1') is False))
    checks.append(check('group creator is manager', a._group_manager(con, 40, 1) is True))
    checks.append(check('ordinary member is not manager', a._group_manager(con, 41, 1) is False))
    checks.append(check('author can delete own group post', a._group_post_owned_or_manager(con, 41, 50, 1, 'WALLET1') is True))
    checks.append(check('member cannot delete another group post', a._group_post_owned_or_manager(con, 41, 51, 1, 'WALLET1') is False))
    checks.append(check('unknown ownership schema remains unknown, never auto-allowed',
                        a._row_owned_by(con, 'users', 1, 1, 'WALLET1') is None))
finally:
    con.close(); os.unlink(path)

src = open('authorization_hardening.py', encoding='utf-8').read()
checks.append(check('mutating message ids are guarded', "method in {'PUT', 'PATCH', 'DELETE'}" in src and '_message_owned' in src))
checks.append(check('notification batch ids are ownership checked', '_notification_ids_owned' in src and 'delete_batch' in src))
checks.append(check('group manager actions have a server-side guard', '_GROUP_MANAGER_ACTIONS' in src and '_group_manager' in src))
checks.append(check('authorization database failure is fail-closed', "503, 'Authorization backend unavailable'" in src))
checks.append(check('unknown ownership result is fail-closed', '_require_proven' in src and "return _deny(503, 'Authorization backend unavailable')" in src))
checks.append(check('user id is re-derived from the authenticated wallet',
                    'SELECT id FROM users WHERE wallet_address=?' in src and 'session.get(' not in src))
checks.append(check('protected mutation requires a DB user bound to proven wallet',
                    "return _deny(403, 'Account not available')" in src))

raise SystemExit(0 if all(checks) else 1)
