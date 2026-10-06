"""Public app-data replies must stay useful without exposing user/account data."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

import platform_assistant as agent
import platform_public_data as public_data
import test_platform_assistant as fixtures


class PublicData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "public.db")
        with sqlite3.connect(self.db) as c:
            c.execute(
                """CREATE TABLE token_calls(
                    id INTEGER PRIMARY KEY,
                    mint TEXT,
                    symbol TEXT,
                    token_name TEXT,
                    price_at_call REAL,
                    peak_price REAL,
                    last_price REAL,
                    timestamp TEXT,
                    post_id INTEGER
                )"""
            )
            c.execute(
                """INSERT INTO token_calls VALUES
                   (1,'mint-old','OLD','Old',1,99,10,datetime('now','-2 days'),1),
                   (2,'mint-a','EMBER','Ember',1,2.5,1.8,CURRENT_TIMESTAMP,7),
                   (3,'mint-b','NOVA','Nova',1,1.4,1.2,CURRENT_TIMESTAMP,8)"""
            )
        self.d = SimpleNamespace(
            DB_FILE=self.db,
            state={"tokens": [
                {"mint": "mint-a", "symbol": "EMBER", "volume24h": 51517, "liquidity": 39585, "change24h": 83.97},
                {"symbol": "AAA", "price_change_24h": 12.5},
                {"symbol": "BBB", "price_change_24h": -31.2},
                {"symbol": "CCC", "price_change_24h": 4.0},
            ]},
            FEE_RATE_TXN=0.01,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_best_call_uses_same_24h_peak_ranking_as_app(self):
        q = public_data.query("what is the best call for today?")
        self.assertEqual(q["kind"], "best_call")
        snap = public_data.fetch(q, self.d)
        self.assertEqual(snap["rows"][0]["symbol"], "EMBER")
        topic, text = agent.answer("@orcagent what is the best call for today?", public=snap)
        self.assertEqual(topic, "calls_live")
        self.assertEqual(
            text,
            "Best call today: $EMBER\n"
            "Peak: +150%\n"
            "Entry: $1\n"
            "Top: $2.5\n"
            "View call: https://orcagent.fun/call/2",
        )
        self.assertNotIn("OLD", text)
        self.assertLessEqual(len(text), 240)
        self.assertEqual(public_data._price(0.00006769), "$0.00006769")
        self.assertEqual(public_data._price(0.000133), "$0.000133")

    def test_best_call_variants_are_simple_explain_chart_and_top3(self):
        explain = public_data.query("why is the best call the best?")
        self.assertEqual(explain, {"kind": "best_call", "variant": "explain"})
        snap = public_data.fetch(explain, self.d)
        topic, text = public_data.render(explain, snap)
        self.assertEqual(topic, "calls_live")
        self.assertIn("Why: Best recorded peak today (+150%)", text)
        self.assertIn("Why: 24h volume $51.5K", text)
        self.assertIn("Why: Liquidity $39.6K", text)

        chart = public_data.query("show me the best call chart")
        self.assertEqual(chart, {"kind": "best_call", "variant": "chart"})
        _, chart_text = public_data.render(chart, public_data.fetch(chart, self.d))
        self.assertIn("Chart: yes", chart_text)

        top = public_data.query("what are the top 3 calls?")
        self.assertEqual(top["kind"], "top_calls")
        _, top_text = public_data.render(top, public_data.fetch(top, self.d))
        self.assertIn("Top 3 calls today:", top_text)
        self.assertIn("1. $EMBER | +150% | /call/2", top_text)
        self.assertIn("2. $NOVA | +40% | /call/3", top_text)
        self.assertIn("View all calls: https://orcagent.fun/calls", top_text)

    def test_no_public_winner_has_clear_trending_fallback(self):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE token_calls SET peak_price=price_at_call WHERE timestamp >= datetime('now','-1 day')")
        q = public_data.query("what is the best call today?")
        _, text = public_data.render(q, public_data.fetch(q, self.d))
        self.assertIn("No clear best call today.", text)
        self.assertIn("View trending: https://orcagent.fun/live-market", text)

    def test_market_movers_and_live_fee_use_public_app_state(self):
        q = public_data.query("what is trending?")
        topic, text = public_data.render(q, public_data.fetch(q, self.d))
        self.assertEqual(topic, "market_live")
        self.assertIn("$BBB -31.2%", text)
        self.assertIn("$AAA +12.5%", text)
        q = public_data.query("what is the current platform fee?")
        topic, text = public_data.render(q, public_data.fetch(q, self.d))
        self.assertEqual(topic, "fees_live")
        self.assertIn("1%", text)

    def test_private_account_questions_never_read_or_return_account_data(self):
        for question in (
            "what is my SOL balance?",
            "show my portfolio",
            "tell me my bot settings",
            "show user wallet history",
            "how much are my referral earnings?",
            "show my DMs",
        ):
            with self.subTest(question=question):
                q = public_data.query(question)
                self.assertEqual(q["kind"], "private")
                # An invalid DB path proves the privacy path performs no account lookup.
                snap = public_data.fetch(q, SimpleNamespace(DB_FILE="/does/not/exist"))
                topic, text = agent.answer("@orcagent " + question, public=snap)
                self.assertEqual(topic, "privacy")
                self.assertIn("never expose user-specific", text)
                self.assertNotIn("SOL:", text)
        self.assertIsNone(public_data.query("what is wallet connect?"))
        self.assertEqual(agent.answer("@orcagent what is wallet connect?")[0], "wallet")

    def test_public_data_module_never_queries_user_private_tables(self):
        source = Path("platform_public_data.py").read_text(encoding="utf-8").lower()
        for sql_fragment in (
            "from users",
            "join users",
            "from trades",
            "from messages",
            "from notifications",
            "from wallet",
            "from referrals",
        ):
            self.assertNotIn(sql_fragment, source)


class ReplyIntegration(unittest.TestCase):
    setUp = fixtures.Assistant.setUp
    tearDown = fixtures.Assistant.tearDown
    source = fixtures.Assistant.source

    def test_best_call_question_is_answered_from_public_call_data(self):
        with sqlite3.connect(self.db) as c:
            c.execute(
                """CREATE TABLE token_calls(
                    id INTEGER PRIMARY KEY,
                    mint TEXT,
                    symbol TEXT,
                    token_name TEXT,
                    price_at_call REAL,
                    peak_price REAL,
                    last_price REAL,
                    timestamp TEXT,
                    post_id INTEGER
                )"""
            )
            c.execute(
                """INSERT INTO token_calls VALUES
                   (5,'mint-ember','EMBER','Ember',0.01,0.025,0.018,CURRENT_TIMESTAMP,1)"""
            )
        source = self.source("@orcagent what is the best call for today?")
        reply_id = agent.reply_to(self.d, source, "member", self.now)
        with sqlite3.connect(self.db) as c:
            message = c.execute(
                "SELECT message FROM feed_replies WHERE id=?", (reply_id,)
            ).fetchone()[0]
        self.assertIn("Best call today: $EMBER", message)
        self.assertIn("Peak: +150%", message)
        self.assertIn("Entry: $0.01", message)
        self.assertIn("Top: $0.025", message)
        self.assertIn("View call: https://orcagent.fun/call/5", message)
        self.assertNotIn("guaranteed", message.lower())


if __name__ == "__main__":
    unittest.main()
