"""Post/reply identity regression: old replies must not attach to reused post IDs.

Uses an isolated SQLite database, never the production database.
"""
import ast
import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path
from flask import Flask, jsonify, request, session

BASE = Path(__file__).resolve().parents[1]
SOURCE = (BASE / 'dashboard.py').read_text()
FUNCTIONS = {n.name: n for n in ast.parse(SOURCE).body
             if isinstance(n, ast.FunctionDef)}


def extract(ns, *names):
    nodes = []
    for name in names:
        n = FUNCTIONS[name]
        n.decorator_list = []
        nodes.append(n)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'dashboard.py', 'exec'), ns)


class ReplyIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / 'replies.db')
        self.app = Flask(__name__)
        self.app.secret_key = 'fixture-only'
        with sqlite3.connect(self.db) as c:
            c.executescript("""
            CREATE TABLE users (id INTEGER PRIMARY KEY, wallet_address TEXT,
                username TEXT, avatar_url TEXT, is_verified INTEGER);
            CREATE TABLE feed_posts (id INTEGER PRIMARY KEY, wallet TEXT,
                content TEXT, created_at TEXT, image_url TEXT, view_count INTEGER DEFAULT 0);
            CREATE TABLE trades (id INTEGER PRIMARY KEY, user_id INTEGER,
                timestamp TEXT, token TEXT, mint_address TEXT,
                entry_price REAL, exit_price REAL, view_count INTEGER DEFAULT 0);
            CREATE TABLE group_posts (id INTEGER PRIMARY KEY, created_at TEXT);
            CREATE TABLE feed_replies (id INTEGER PRIMARY KEY, post_id TEXT,
                user_id INTEGER, message TEXT, created_at TEXT,
                parent_reply_id INTEGER);
            CREATE TABLE feed_reply_likes (id INTEGER PRIMARY KEY, user_id INTEGER, reply_id INTEGER);
            CREATE TABLE post_likes (id INTEGER PRIMARY KEY, post_id TEXT, user_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,post_id));
            CREATE TABLE post_reactions (id INTEGER PRIMARY KEY, post_id TEXT, user_id INTEGER, emoji TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id,post_id,emoji));
            CREATE TABLE feed_reposts (id INTEGER PRIMARY KEY,
                post_id TEXT, reposter_wallet TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO users VALUES (1, 'wallet-one', 'Tester', '', 0);
            INSERT INTO users VALUES (2, 'wallet-two', 'Second', '', 0);
            INSERT INTO feed_posts VALUES
                (450, 'wallet-one', 'New September post', '2026-09-19 18:48:36', NULL, 2),
                (451, 'wallet-one', 'Another post', '2026-09-20 01:00:00', NULL, 0);
            INSERT INTO trades VALUES
                (832, 1, '2026-09-18T17:01:46Z', 'GUMBUS', 'mint', 1, 2, 0);
            INSERT INTO group_posts VALUES (9, '2026-09-19 18:48:36');
            INSERT INTO feed_replies VALUES
                (3, 'p450', 1, 'Historic June reply', '2026-06-29 16:49:26', NULL),
                (4, 'p450', 1, 'Valid September reply', '2026-09-19 20:00:00', NULL),
                (5, 't832', 1, 'Valid ISO trade reply', '2026-09-18 17:02:00', NULL),
                (6, 'g9', 1, 'Old group reply', '2026-06-29 16:49:26', NULL);
            INSERT INTO feed_reply_likes VALUES (1, 1, 3);
            INSERT INTO post_likes VALUES
                (1, 'p450', 1, '2026-06-29 16:49:26'),
                (2, 'p450', 2, '2026-09-19 20:00:00'),
                (3, 'p451', 1, '2026-06-29 16:49:26');
            INSERT INTO post_reactions VALUES
                (1, 'p450', 1, '🔥', '2026-06-29 16:49:26'),
                (2, 'p450', 2, '❤️', '2026-09-19 20:00:00');
            INSERT INTO feed_reposts VALUES
                (2, 'p450', 'wallet-one', '2026-06-29 16:49:26'),
                (3, 'p450', 'wallet-two', '2026-09-19 21:00:00');
            """)
        self.ns = {
            'sqlite3': sqlite3, 'DB_FILE': self.db,
            'jsonify': jsonify, 'request': request, 'session': session,
            'datetime': datetime,
            '_authenticated_wallet': lambda: 'wallet-one',
            '_current_wallet': lambda: 'wallet-one',
            '_get_uid': lambda c, w: 1,
            '_group_post_access_ok': lambda c, pid, uid: True,
            '_team_roles_for_wallets': lambda wallets: {},
            '_sanitize': lambda value: value,
            '_post_owner_uid': lambda c, pid: None,
            '_REACTION_EMOJIS': frozenset(('🔥', '❤️')),
            're': __import__('re'),
            '_send_push_notification': lambda *a, **k: None,
        }
        extract(self.ns, '_feed_post_created_at', '_valid_post_interaction_sql',
                '_require_interaction_post', '_delete_feed_post_interactions',
                'get_feed_replies', 'post_feed_reply', '_notify_reply_mentions',
                'social_feed', 'get_feed_post',
                'get_feed_likes', 'get_feed_like_users', 'feed_reactions_batch',
                'toggle_feed_like', 'toggle_feed_repost', 'toggle_feed_reaction')

    def test_reply_list_hides_old_reply_but_keeps_real_replies(self):
        with self.app.test_request_context('/api/feed/replies/p450'):
            result = self.ns['get_feed_replies']('p450')
            self.assertEqual(result.json['ok'], True)
            self.assertEqual([r['id'] for r in result.json['replies']], [4])
        with self.app.test_request_context('/api/feed/replies/t832'):
            result = self.ns['get_feed_replies']('t832')
            self.assertEqual([r['id'] for r in result.json['replies']], [5])
        with self.app.test_request_context('/api/feed/replies/g9'):
            result = self.ns['get_feed_replies']('g9')
            self.assertEqual(result.json['replies'], [])
        with self.app.test_request_context('/api/feed/replies/p9999'):
            self.assertEqual(self.ns['get_feed_replies']('p9999')[1], 404)

    def test_feed_and_deep_link_counts_use_only_valid_replies(self):
        with self.app.test_request_context('/api/social/feed?filter=all'):
            result = self.ns['social_feed']()
            feed = result.json['items']
            post = next(p for p in feed if p['id'] == 450 and p['type'] == 'text')
            trade = next(p for p in feed if p['id'] == 832)
            self.assertEqual(post['reply_count'], 1)
            self.assertEqual(post['last_reply_at'], '2026-09-19 20:00:00')
            self.assertEqual(trade['reply_count'], 1)
        with self.app.test_request_context('/api/feed/post/p450'):
            self.assertEqual(self.ns['get_feed_post']('p450').json['post']['reply_count'], 1)
        with self.app.test_request_context('/api/feed/post/t832'):
            self.assertEqual(self.ns['get_feed_post']('t832').json['post']['reply_count'], 1)

    def test_old_likes_reactions_and_reposts_do_not_reappear(self):
        with self.app.test_request_context('/api/social/feed?filter=all'):
            posts = self.ns['social_feed']().json['items']
        post = next(p for p in posts if p['id']==450 and p['type']=='text')
        newer = next(p for p in posts if p['id']==451 and p['type']=='text')
        self.assertEqual((post['like_count'], post['repost_count'],post['liked_by_me'],
                          post['reposted_by_me']), (1,1,False,False))
        self.assertEqual(newer['like_count'],0)
        self.assertFalse(any(p.get('type')=='repost' and p['id']==2 for p in posts))
        with self.app.test_request_context('/api/feed/likes/p450'):
            self.assertEqual(self.ns['get_feed_likes']('p450').json,
                             {'ok':True,'count':1,'liked':False})
        with self.app.test_request_context('/api/feed/likes/p450/users'):
            self.assertEqual([u['user_id'] for u in
                              self.ns['get_feed_like_users']('p450').json['users']],[2])
        with self.app.test_request_context('/api/feed/post/p450'):
            self.assertEqual(self.ns['get_feed_post']('p450').json['post']['like_count'],1)
        with self.app.test_request_context('/api/feed/reactions/batch?ids=p450,p451'):
            data=self.ns['feed_reactions_batch']().json['reactions']
            self.assertEqual(data['p450'], {'counts':{'❤️':1}, 'mine':[]})
            self.assertEqual(data['p451'], {'counts':{}, 'mine':[]})
        with self.app.test_request_context('/api/feed/like/p450',method='POST'):
            data=self.ns['toggle_feed_like']('p450').json
            self.assertTrue(data['liked'])
            self.assertEqual(data['count'],2)
        with self.app.test_request_context('/api/feed/repost/p450',method='POST'):
            data=self.ns['toggle_feed_repost']('p450').json
            self.assertTrue(data['reposted'])
            self.assertEqual(data['count'],2)
        with self.app.test_request_context('/api/feed/react/p450',method='POST',json={'emoji':'🔥'}):
            data=self.ns['toggle_feed_reaction']('p450').json
            self.assertTrue(data['active'])
            self.assertEqual(data['counts'],{'🔥':1,'❤️':1})

    def test_new_reply_rejects_stale_parent_and_missing_post(self):
        with self.app.test_request_context('/api/feed/reply', method='POST',
                 json={'post_id':'p450', 'message':'Nested', 'parent_reply_id':3}):
            self.assertEqual(self.ns['post_feed_reply']()[1], 400)
        with self.app.test_request_context('/api/feed/reply', method='POST',
                 json={'post_id':'p9999', 'message':'Orphan'}):
            self.assertEqual(self.ns['post_feed_reply']()[1], 404)
        with self.app.test_request_context('/api/feed/reply', method='POST',
                 json={'post_id':'p450', 'message':'Nested', 'parent_reply_id':4}):
            self.assertEqual(self.ns['post_feed_reply']().json['ok'], True)

    def test_deleting_post_cleans_replies_likes_and_reposts_together(self):
        with sqlite3.connect(self.db) as conn:
            self.ns['_delete_feed_post_interactions'](conn,'p450')
            conn.execute('DELETE FROM feed_posts WHERE id=450')
            conn.commit()
            for table in ('feed_replies','post_likes','post_reactions','feed_reposts'):
                self.assertEqual(conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE post_id='p450'"
                ).fetchone()[0],0,table)
            self.assertEqual(conn.execute(
                'SELECT COUNT(*) FROM feed_reply_likes'
            ).fetchone()[0],0)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM feed_replies WHERE post_id='t832'"
            ).fetchone()[0],1)

if __name__ == '__main__':
    unittest.main()
