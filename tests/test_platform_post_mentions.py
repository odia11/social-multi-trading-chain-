import concurrent.futures
import sqlite3
import unittest
from unittest.mock import patch
from flask import Flask,request
import test_platform_assistant as fixtures
import platform_assistant as p

class PostMentions(unittest.TestCase):
    setUp=fixtures.Assistant.setUp
    tearDown=fixtures.Assistant.tearDown
    source=fixtures.Assistant.source
    def post(self,text='@Orcagent how are you ?',wallet='member'):
        with sqlite3.connect(self.db) as c:
            return c.execute("INSERT INTO feed_posts(wallet,content,created_at) VALUES(?,?,'2026-10-04 01:00:00')",(wallet,text)).lastrowid
    def test_screenshot_greeting_gets_one_english_comment_and_notification(self):
        pid=self.post()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            replies=list(pool.map(lambda _:p.reply_to_post(self.d,pid,'member',self.now),range(4)))
        self.assertEqual(sum(r is not None for r in replies),1)
        with sqlite3.connect(self.db) as c:
            reply=c.execute('SELECT user_id,post_id,parent_reply_id,message FROM feed_replies').fetchone()
            self.assertEqual(reply[:3],(1,'p'+str(pid),None))
            self.assertIn("I'm ready to help",reply[3])
            self.assertEqual(c.execute('SELECT COUNT(*) FROM notifications').fetchone()[0],1)
        for text in ['@orcagent hello','@orcagent hoe gaat het?','@orcagent how are you?']:
            self.assertEqual(p.answer(text)[0],'welcome')
    def test_post_and_comment_share_reply_limits(self):
        for _ in range(2):
            self.assertIsNotNone(p.reply_to_post(self.d,self.post(),'member',self.now))
        self.assertIsNone(p.reply_to(self.d,self.source(),'member',self.now))
        self.assertIsNone(p.reply_to_post(self.d,self.post(),'member',self.now))
    def test_no_tag_wrong_wallet_official_missing_identity_and_embeds_are_excluded(self):
        self.assertIsNone(p.reply_to_post(self.d,self.post('hello'),'member',self.now))
        self.assertIsNone(p.reply_to_post(self.d,self.post(),'other',self.now))
        self.assertIsNone(p.reply_to_post(self.d,self.post(wallet='official'),'official',self.now))
        self.assertIsNone(p.reply_to_post(self.d,self.post('hello __CHART__{"name":"@orcagent"}'),'member',self.now))
        self.assertIsNone(p.reply_to_post(self.d,999,'member',self.now))
        with sqlite3.connect(self.db) as c:c.execute('UPDATE users SET is_verified=0 WHERE id=1')
        self.assertIsNone(p.reply_to_post(self.d,self.post(),'member',self.now))
    def test_followup_context_from_tagged_post_and_unknown_post_clarification(self):
        pid=self.post('@orcagent sharing?')
        bot=p.reply_to_post(self.d,pid,'member',self.now)
        follow=self.source('@orcagent where do I find that?',post='p'+str(pid))
        with sqlite3.connect(self.db) as c:c.execute('UPDATE feed_replies SET parent_reply_id=? WHERE id=?',(bot,follow))
        response=p.reply_to(self.d,follow,'member',self.now)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT topic FROM platform_assistant_events WHERE reply_id=?',(response,)).fetchone()[0],'share')
        pid=self.post('@orcagent how can I spread my idea?')
        bot=p.reply_to_post(self.d,pid,'member',self.now+901)
        clar=self.source('@orcagent I mean sharing',post='p'+str(pid))
        with sqlite3.connect(self.db) as c:c.execute('UPDATE feed_replies SET parent_reply_id=? WHERE id=?',(bot,clar))
        self.assertIsNotNone(p.reply_to(self.d,clar,'member',self.now+901))
    def test_authenticated_post_hook_and_failure_isolation(self):
        app=Flask(__name__);self.d.app=app
        self.d._authenticated_wallet=lambda:request.headers.get('Test-Wallet')
        @app.post('/api/feed/post')
        def create():
            if not self.d._authenticated_wallet():return {'ok':False},401
            return {'ok':True,'id':self.post(request.json['content'])}
        with patch('threading.Thread.start'):p.install(self.d)
        client=app.test_client()
        self.assertEqual(client.post('/api/feed/post',json={'content':'@orcagent hello'}).status_code,401)
        r=client.post('/api/feed/post',json={'content':'@orcagent hello'},headers={'Test-Wallet':'member'})
        self.assertIn('platform_reply_id',r.json)
        with patch.object(p,'reply_to_post',side_effect=RuntimeError('unavailable')):
            r=client.post('/api/feed/post',json={'content':'@orcagent hello'},headers={'Test-Wallet':'member'})
            self.assertEqual(r.status_code,200);self.assertTrue(r.json['ok'])
