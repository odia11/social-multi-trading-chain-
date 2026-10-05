"""Question specificity and event-driven price notifications."""
import ast
from pathlib import Path
import threading
import time
import unittest
import platform_assistant as agent
import protection_exits as exits

class Questions(unittest.TestCase):
    def test_specific_actions_override_broad_words(self):
        cases = [
            ('how do I sell tokens from my wallet?', 'trading', 'tap Sell'),
            ('what fees do I pay when I buy?', 'fees', 'network costs'),
            ('my portfolio is not showing all tokens', 'portfolio', 'Which token is missing'),
            ('how do I disconnect my wallet?', 'wallet', 'Disconnect'),
            ('how do I publish a call?', 'calls', 'Tap POST'),
            ('how do I save a call card?', 'share', 'Save card'),
            ('how do I tag someone in a reply?', 'community', 'suggestions'),
            ('where does the reply notification go?', 'community', 'highlighted reply'),
            ('do creators get paid for likes?', 'creator', 'does not earn'),
            ('is my referral 20% of trading volume?', 'referral', 'not 20%'),
            ('why did my stoploss fail?', 'trading', 'stays open until confirmed'),
        ]
        for question, topic, phrase in cases:
            with self.subTest(question=question):
                actual, text = agent.answer('@orcagent '+question)
                self.assertEqual(actual, topic)
                self.assertIn(phrase, text)
                self.assertLessEqual(len(text), 240)
    def test_followup_steps_do_not_repeat_general_overview(self):
        topic, text = agent.answer('@orcagent where do I find that?', 'share')
        self.assertEqual(topic, 'share')
        self.assertIn('Share call', text)
        self.assertEqual(agent.answer('@orcagent where do I find that?')[0], 'scope')
        self.assertEqual(agent.answer('@orcagent what is the meaning of life?', 'share')[0], 'scope')
        self.assertEqual(agent.answer('@orcagent how do I sell?', 'share')[0], 'trading')
    def test_secrets_and_english_still_take_priority(self):
        self.assertEqual(agent.answer('@orcagent buy with my private key')[0], 'secrets')
        self.assertIn('choose the amount', agent.answer('@orcagent hoe kan ik verkopen?')[1])
        self.assertIsNone(agent.answer('how do I sell?'))
    def test_unknown_question_requests_detail(self):
        topic, text = agent.answer('@orcagent why is this happening?')
        self.assertEqual(topic, 'scope')
        self.assertIn('question', text)

class PriceNotifications(unittest.TestCase):
    def test_one_tick_wakes_all_monitors_without_poll_wait(self):
        revision = exits.price_revision()
        ready = threading.Barrier(4)
        results = []
        def monitor():
            ready.wait()
            start = time.monotonic()
            results.append((exits.wait_for_price(revision, 1), time.monotonic()-start))
        threads = [threading.Thread(target=monitor) for _ in range(3)]
        for t in threads: t.start()
        ready.wait()
        exits.price_updated()
        for t in threads: t.join(2)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(ok and duration < .2 for ok, duration in results))
    def test_actual_watcher_rechecks_on_tick_before_long_fallback(self):
        tree = ast.parse(Path('dashboard.py').read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_exit_watch')
        stop = threading.Event()
        ready = threading.Event()
        hit = threading.Event()
        calls = []
        def check():
            calls.append(time.monotonic())
            if len(calls) == 1:
                ready.set()
            else:
                hit.set()
                stop.set()
        ctx = dict(stop_event=stop, time=time, EXIT_CHECK_INTERVAL=1,
                   _price_revision=exits.price_revision, _wait_for_price=exits.wait_for_price,
                   _exit_pass=check, short='test')
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<watcher>', 'exec'), ctx)
        thread = threading.Thread(target=ctx['_exit_watch'])
        thread.start()
        self.assertTrue(ready.wait(1))
        exits.price_updated()
        self.assertTrue(hit.wait(.2))
        thread.join(1)
        self.assertFalse(thread.is_alive())

    def test_tick_during_threshold_pass_cannot_be_lost(self):
        revision = exits.price_revision()
        exits.price_updated()
        start = time.monotonic()
        self.assertTrue(exits.wait_for_price(revision, 1))
        self.assertLess(time.monotonic()-start, .05)
    def test_idle_monitors_sleep_instead_of_busy_polling(self):
        start = time.monotonic()
        self.assertFalse(exits.wait_for_price(exits.price_revision(), .08))
        self.assertGreaterEqual(time.monotonic()-start, .07)

if __name__ == '__main__':
    unittest.main()
