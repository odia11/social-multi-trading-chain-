import logging
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from deposit_notifications import _schema, _register_wallets, _dispatch_pending, record

class PushTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.NamedTemporaryFile()
        self.d=SimpleNamespace(DB_FILE=self.temp.name,app=SimpleNamespace(logger=logging.getLogger('test')),
            _send_push_notification=Mock(),_wallet_tokens_cache={'alice':{'old':True},'bob':{'old':True}})
        with sqlite3.connect(self.temp.name) as c:
            c.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,encrypted_private_key TEXT,created_at TEXT);
            INSERT INTO users VALUES(1,'alice','key','1970-01-01 00:01:00'),(2,'bob','key','1970-01-01 00:02:00'),(3,'readonly','','1970-01-01');
            CREATE TABLE notifications(user_id INTEGER,type TEXT,content TEXT,link TEXT);""")
            _schema(c)
        self.event=dict(id='tx1',type='receive',status='confirmed',timestamp=110,amount=2,currency='SOL')

    def tearDown(self):self.temp.close()

    def test_offline_members_registered_before_their_first_notification_poll(self):
        _register_wallets(self.d,100)
        with sqlite3.connect(self.temp.name) as c:
            self.assertEqual(c.execute('SELECT user_id,since FROM deposit_watch ORDER BY user_id').fetchall(),[(1,60),(2,120)])
        _register_wallets(self.d,200000)
        with sqlite3.connect(self.temp.name) as c:
            self.assertEqual(c.execute('SELECT since FROM deposit_watch WHERE user_id=1').fetchone()[0],60)

    def test_one_inbox_one_push_and_only_recipient_cache_invalidated(self):
        record(self.d,'alice',[],100)
        record(self.d,'alice',[self.event],101)
        record(self.d,'alice',[self.event],102)
        self.d._send_push_notification.assert_called_once()
        args=self.d._send_push_notification.call_args
        self.assertEqual(args.args[:3],(1,'Funds received','You received 2 SOL'))
        self.assertTrue(args.kwargs['tag'].startswith('deposit-'))
        self.assertNotIn('alice',self.d._wallet_tokens_cache)
        self.assertIn('bob',self.d._wallet_tokens_cache)
        with sqlite3.connect(self.temp.name) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)

    def test_failed_push_can_retry_without_duplicate_inbox(self):
        self.d._send_push_notification.side_effect=RuntimeError('dispatch unavailable')
        record(self.d,'alice',[self.event],100)
        with sqlite3.connect(self.temp.name) as c:
            self.assertEqual(c.execute('SELECT dispatched FROM deposit_push_queue').fetchone()[0],0)
        self.d._send_push_notification.side_effect=None
        _dispatch_pending(self.d)
        _dispatch_pending(self.d)
        self.assertEqual(self.d._send_push_notification.call_count,2)
        with sqlite3.connect(self.temp.name) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)

if __name__=='__main__':unittest.main()
