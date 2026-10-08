"""OrcAgent's feed posts talk about calls and trending tokens, and are never the same.

Every 30 minutes OrcAgent posts. Before, it rotated through fixed product
texts, so the feed showed the same words again every day. Now each slot is
the best live post from the app's own public data -- a call milestone, a new
call, a trending token, the best call of the day, the most called token, the
top caller of the week, a market pulse -- with a product text only when
nothing is live, and never a text OrcAgent has posted before.
"""
import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import platform_assistant as p
import platform_live_posts as live

DAY0 = dt.datetime(2026, 10, 8, 0, 0, tzinfo=p.TZ)


def ts(when):
    return when.astimezone(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def token(sym, mint, chg, vol=2_000_000, liq=400_000, mc=40_000_000, px=0.0021):
    return {'mint': mint, 'symbol': sym, 'name': sym.title(), 'price_usd': px, 'price_change_24h': chg,
            'volume_24h': vol, 'liquidity_usd': liq, 'market_cap': mc, 'buys_24h': 600, 'sells_24h': 400,
            'pair_address': 'P' + mint[:10], 'image_url': ''}


TOKENS = [token('POPCAT', 'M' * 40 + 'pop1', 46.8), token('WIF', 'M' * 40 + 'wif1', 12.5, px=1.97),
          token('BONK', 'M' * 40 + 'bonk', -3.2, px=0.0000231), token('GOAT', 'M' * 40 + 'goat', 8.1)]


class LivePosts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / 'live.db')
        with sqlite3.connect(self.db) as c:
            c.executescript("""
CREATE TABLE users(id INTEGER PRIMARY KEY,wallet_address TEXT,username TEXT,is_verified INTEGER);
INSERT INTO users VALUES(1,'officialwalletaddr111111111111111111111','Orcagent',1),
  (2,'chartwizardwalletaddr22222222222222222','chartwizard',1),(3,'solqueenwalletaddr3333333333333333333','solqueen',0),
  (4,'nonamewalletaddr44444444444444444444',NULL,0);
CREATE TABLE feed_posts(id INTEGER PRIMARY KEY AUTOINCREMENT,wallet TEXT,content TEXT,created_at TEXT,image_url TEXT);
CREATE TABLE feed_replies(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,post_id TEXT,message TEXT,created_at TEXT,parent_reply_id INTEGER);
CREATE TABLE notifications(user_id INTEGER,type TEXT,content TEXT,link TEXT,actor_wallet TEXT);
CREATE TABLE token_calls(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,wallet TEXT,mint TEXT,symbol TEXT,
  token_name TEXT,price_at_call REAL,mcap_at_call REAL,peak_price REAL,peak_at TEXT,timestamp TEXT,note TEXT,
  chain TEXT,image_url TEXT,last_price REAL,post_id INTEGER);
""")
        p.initialize(self.db)
        self.addCleanup(self.tmp.cleanup)

    def call(self, uid, sym, p0, peak, when, note='', mc=1_000_000):
        with sqlite3.connect(self.db) as c:
            return c.execute('INSERT INTO token_calls(user_id,wallet,mint,symbol,token_name,price_at_call,mcap_at_call,'
                             'peak_price,timestamp,note,chain,last_price) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                             (uid, 'w', 'MINT' + sym, sym, sym, p0, mc, peak, ts(when), note, 'solana', peak)).lastrowid

    def posts(self):
        with sqlite3.connect(self.db) as c:
            return [r[0] for r in c.execute("SELECT content FROM feed_posts WHERE wallet LIKE 'official%' ORDER BY id")]

    def topics(self):
        with sqlite3.connect(self.db) as c:
            return [r[0] for r in c.execute("SELECT topic FROM platform_assistant_events WHERE kind='post' ORDER BY created_at")]

    def publish(self, when, tokens=TOKENS, sol=152.0):
        return p.publish_due(self.db, when.timestamp(), live_data=lambda: (tokens, sol))

    def test_a_call_milestone_and_a_new_call_go_out_first_and_only_once(self):
        cid = self.call(2, 'POPCAT', 0.0001, 0.00024, DAY0 - dt.timedelta(days=2), mc=141_000_000)
        new = self.call(3, 'FWOG', 0.04, 0.041, DAY0 - dt.timedelta(minutes=40), note='Volume picking up, holding support.')
        self.publish(DAY0)
        self.publish(DAY0 + dt.timedelta(minutes=30))
        first, second = self.posts()
        self.assertIn('$POPCAT', first)
        self.assertIn('2.4x', first)   # where it stands now, not the rounded milestone
        self.assertIn('@chartwizard', first)
        self.assertTrue(first.endswith('__CALL__' + json.dumps({'id': cid})))
        self.assertIn('@solqueen', second)
        self.assertIn('Volume picking up, holding support.', second)
        self.assertTrue(second.endswith('__CALL__' + json.dumps({'id': new})))
        self.assertEqual(self.topics()[:2], ['milestone:%d:2' % cid, 'call:%d' % new])
        for i in range(2, 10):
            self.publish(DAY0 + dt.timedelta(minutes=30 * i))
        self.assertEqual(self.topics().count('milestone:%d:2' % cid), 1)
        self.assertEqual(self.topics().count('call:%d' % new), 1)

    def test_trending_tokens_rotate_with_a_live_chart_and_a_cooldown(self):
        for i in range(4):
            self.publish(DAY0 + dt.timedelta(minutes=30 * i))
        trending = [t for t in self.topics() if t.startswith('trending:')]
        self.assertEqual(len(trending), len(set(trending)))
        self.assertGreaterEqual(len(trending), 2)
        self.assertNotIn('trending:' + TOKENS[2]['mint'], trending, 'a falling token was called trending')
        post = next(x for x in self.posts() if '__CHART__' in x)
        chart = json.loads(post.split('__CHART__', 1)[1])
        self.assertEqual(chart['chain'], 'solana')
        self.assertIn(chart['mint'], {t['mint'] for t in TOKENS})
        self.assertIn('Not financial advice.', post.split('__CHART__')[0])

    def test_a_whole_day_of_posts_is_all_different_and_about_calls_and_trending(self):
        self.call(2, 'POPCAT', 0.0001, 0.00016, DAY0 - dt.timedelta(hours=1), mc=141_000_000)
        self.call(3, 'POPCAT', 0.00012, 0.00013, DAY0 - dt.timedelta(hours=2))
        self.call(2, 'WIF', 1.5, 2.6, DAY0 - dt.timedelta(days=3))
        for i in range(48):
            self.publish(DAY0 + dt.timedelta(minutes=30 * i))
        posts = self.posts()
        self.assertEqual(len(posts), len(set(posts)), 'OrcAgent posted the same text twice')
        live_count = sum(1 for t in self.topics() if ':' in t)
        self.assertGreaterEqual(live_count, 12)
        kinds = {t.split(':')[0] for t in self.topics() if ':' in t}
        self.assertTrue({'trending', 'call'} <= kinds, kinds)
        per_mint = {}
        for t in self.topics():
            if t.startswith('trending:'):
                per_mint[t] = per_mint.get(t, 0) + 1
        self.assertTrue(all(n <= 4 for n in per_mint.values()), per_mint)
        self.assertEqual(sum(1 for t in self.topics() if t.startswith('mostcalled:')), 1)
        openings = [' '.join(x.split()[:3]).lower() for x in posts]
        self.assertTrue(all(a != b for a, b in zip(openings, openings[1:])), 'two posts in a row opened the same way')

    def test_never_posts_wallets_or_unnamed_users(self):
        self.call(4, 'ANON', 0.001, 0.005, DAY0 - dt.timedelta(minutes=20))
        for i in range(12):
            self.publish(DAY0 + dt.timedelta(minutes=30 * i))
        everything = '\n'.join(self.posts())
        self.assertNotIn('walletaddr', everything)
        self.assertNotIn('$ANON', everything)

    def test_nothing_live_falls_back_to_product_texts_that_never_repeat(self):
        out = [p.publish_due(self.db, (DAY0 + dt.timedelta(minutes=30 * i)).timestamp(), live_data=lambda: ([], 0.0))
               for i in range(len(p.THESES) + 4)]
        posts = self.posts()
        self.assertEqual(len(posts), len(p.THESES))
        self.assertEqual(len(set(posts)), len(posts))
        self.assertTrue(all(o is None for o in out[-4:]))

    def test_a_failing_price_source_does_not_stop_the_post(self):
        def broken():
            raise RuntimeError('scanner down')
        self.assertIsNotNone(p.publish_due(self.db, DAY0.timestamp(), live_data=broken))

    def test_call_and_trending_posts_carry_a_designed_picture_instead_of_the_card(self):
        cid = self.call(2, 'POPCAT', 0.0001, 0.00024, DAY0 - dt.timedelta(days=2), mc=141_000_000)
        seen = []
        def render(media, seed, variant):
            seen.append((media['kind'], seed, variant))
            return '/media/agent/%040x.webp' % len(seen)
        for i in range(3):
            p.publish_due(self.db, (DAY0 + dt.timedelta(minutes=30 * i)).timestamp(),
                          live_data=lambda: (TOKENS, 152.0), render=render)
        with sqlite3.connect(self.db) as c:
            rows = c.execute("SELECT content, image_url FROM feed_posts WHERE wallet LIKE 'official%' ORDER BY id").fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(img and img.startswith('/media/agent/') for _, img in rows))
        # The picture replaces the card, but the post still says which call or
        # token it is about, so "$SYMBOL" opens exactly that one.
        self.assertTrue(rows[0][0].endswith('__CALL__' + json.dumps({'id': cid})))
        self.assertTrue(all('__CALL__' in t or '__CHART__' in t for t, _ in rows))
        self.assertEqual(seen[0][0], 'call')
        self.assertIn('trending', [k for k, _, _ in seen])
        self.assertEqual(len({s for _, s, _ in seen}), 3)   # each picture its own seed
        trend = [v for k, _, v in seen if k == 'trending']
        self.assertEqual(trend, list(range(len(trend))))   # designs taken in turn

    def test_a_picture_that_cannot_be_drawn_falls_back_to_the_live_card(self):
        cid = self.call(2, 'POPCAT', 0.0001, 0.00024, DAY0 - dt.timedelta(days=2))
        def broken(media, seed, variant):
            raise RuntimeError('logo host down')
        p.publish_due(self.db, DAY0.timestamp(), live_data=lambda: (TOKENS, 152.0), render=broken)
        with sqlite3.connect(self.db) as c:
            content, img = c.execute("SELECT content, image_url FROM feed_posts WHERE wallet LIKE 'official%'").fetchone()
        self.assertIsNone(img)
        self.assertTrue(content.endswith('__CALL__' + json.dumps({'id': cid})))

    def test_a_milestone_is_posted_only_while_the_token_is_still_there(self):
        # $Sirius: called at $8.98K, peaked at 8.48x, then fell to $3.2K -- and
        # was still posted as "5x on the call".
        crashed = self.call(2, 'SIRIUS', 0.0001, 0.000848, DAY0 - dt.timedelta(days=5), mc=8_980)
        with sqlite3.connect(self.db) as c:
            c.execute('UPDATE token_calls SET last_price=? WHERE id=?', (0.0000357, crashed))
        holding = self.call(3, 'HOLD', 0.0001, 0.0007, DAY0 - dt.timedelta(days=1), mc=10_000)
        with sqlite3.connect(self.db) as c:
            c.execute('UPDATE token_calls SET last_price=? WHERE id=?', (0.0006, holding))
            out = live.milestone(c, DAY0.timestamp())
        topics = [o[0] for o in out]
        self.assertNotIn('milestone:%d:5' % crashed, topics)
        self.assertFalse(any(t.startswith('milestone:%d:' % crashed) for t in topics))
        self.assertIn('milestone:%d:5' % holding, topics)
        text = ' '.join(next(o[1] for o in out if o[0] == 'milestone:%d:5' % holding))
        self.assertIn('6x', text)          # the real multiple, not the milestone's
        self.assertNotIn('8.48x', text)

    def test_the_most_called_token_post_names_its_latest_call(self):
        self.call(2, 'ATTN+', 0.001, 0.002, DAY0 - dt.timedelta(hours=3))
        last = self.call(3, 'ATTN+', 0.0012, 0.0013, DAY0 - dt.timedelta(hours=1))
        with sqlite3.connect(self.db) as c:
            out = live.most_called(c, DAY0.timestamp())
        self.assertEqual(len(out), 1)
        self.assertIn('$ATTN+', ' '.join(out[0][1]))
        self.assertEqual(out[0][3], '\n__CALL__' + json.dumps({'id': last}))

    def test_earlier_posts_get_the_marker_of_their_call_or_token_once(self):
        cid = self.call(2, 'Attention+', 0.0001, 0.001, DAY0 - dt.timedelta(days=3))
        mint = TOKENS[0]['mint']
        posts = {}
        with sqlite3.connect(self.db) as c:
            for topic, text in (('milestone:%d:10' % cid, '$Attention+ just hit 10x since @chartwizard called it.'),
                                ('trending:' + mint, '$POPCAT+ is trending on Solana.'),
                                ('pulse:1', 'Market pulse: quiet day.')):
                pid = c.execute("INSERT INTO feed_posts(wallet,content,image_url) VALUES"
                                "('officialwalletaddr111111111111111111111',?,'/media/agent/x.webp')", (text,)).lastrowid
                c.execute('INSERT INTO platform_assistant_events VALUES(?,?,?,?,?,?,?)',
                          (topic, 'post', None, 'p%d' % pid, None, topic, 0))
                posts[topic.split(':')[0]] = pid
            member = c.execute("INSERT INTO feed_posts(wallet,content) VALUES('w','$Attention+ to the moon')").lastrowid
            c.execute("DELETE FROM platform_assistant_settings WHERE key='token_marker_backfill_v1'")
        p.initialize(self.db)
        p.initialize(self.db)   # a second start changes nothing more
        with sqlite3.connect(self.db) as c:
            got = {k: c.execute('SELECT content FROM feed_posts WHERE id=?', (v,)).fetchone()[0] for k, v in posts.items()}
            mem = c.execute('SELECT content FROM feed_posts WHERE id=?', (member,)).fetchone()[0]
        self.assertTrue(got['milestone'].endswith('called it.\n__CALL__' + json.dumps({'id': cid})))
        chart = json.loads(got['trending'].split('__CHART__', 1)[1])
        self.assertEqual((chart['symbol'], chart['mint']), ('POPCAT+', mint))
        self.assertEqual(got['pulse'], 'Market pulse: quiet day.')
        self.assertEqual(mem, '$Attention+ to the moon')
        self.assertEqual(got['milestone'].count('__CALL__'), 1)

    def test_formatting(self):
        self.assertEqual(live.price(0.000207), '$0.0002070')
        self.assertEqual(live.price(152), '$152.00')
        self.assertEqual(live.usd(141e6), '$141M')
        self.assertEqual(live.usd(8.28e6), '$8.28M')
        self.assertEqual(live.mult(2.0), '2x')
        self.assertEqual(live.pct(-6.4), '-6.4%')


if __name__ == '__main__':
    unittest.main()
