import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from deposit_notifications import record, _schema, _register_wallets, _dispatch_pending

class DepositNotificationsTest(unittest.TestCase):
    def test_confirmed_only_deduplicated_private_and_no_history_spam(self):
        with tempfile.NamedTemporaryFile() as db:
            d = SimpleNamespace(DB_FILE=db.name)
            with sqlite3.connect(db.name) as c:
                c.executescript('''CREATE TABLE users(id INTEGER, wallet_address TEXT);
                INSERT INTO users VALUES(1,'alice'),(2,'bob');
                CREATE TABLE notifications(user_id INTEGER,type TEXT,content TEXT,link TEXT);
                CREATE TABLE deposit_watch(user_id INTEGER PRIMARY KEY,since REAL);
                CREATE TABLE deposit_notice(user_id INTEGER,event_id TEXT,PRIMARY KEY(user_id,event_id));''')
            with sqlite3.connect(db.name) as c:
                _schema(c)
            record(d, 'alice', [], 100)
            base = dict(type='receive',status='confirmed',timestamp=101,amount=5,currency='tokens',id='tx:mint')
            events = [base, dict(base,id='old',timestamp=99),dict(base,id='out',type='send'),dict(base,id='pending',status='pending')]
            record(d, 'alice', events, 102)
            record(d, 'alice', events, 103)
            with sqlite3.connect(db.name) as c:
                self.assertEqual(c.execute('SELECT user_id,type,content FROM notifications').fetchall(),[(1,'deposit','You received 5 tokens')])
                self.assertEqual(c.execute('SELECT since FROM deposit_watch').fetchone()[0],100)

if __name__ == '__main__':
    unittest.main()
