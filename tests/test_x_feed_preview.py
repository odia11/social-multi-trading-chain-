"""Native X preview safety, availability, cache and server wiring."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask
import x_feed_preview as x

RAW = {'id_str': '1234567890123456789', 'text': 'A real post https://t.co/photo',
       'created_at': '2026-10-10T18:36:00Z',
       'user': {'name': 'Test', 'screen_name': 'test', 'profile_image_url_https': 'https://pbs.twimg.com/a.png'},
       'photos': [{'url': 'https://pbs.twimg.com/media/a.jpg', 'width': 800, 'height': 1200}],
       'entities': {'media': [{'url': 'https://t.co/photo'}]}}

class PreviewTests(unittest.TestCase):
    def setUp(self):
        x._CACHE.clear()
        self.app = Flask(__name__)
        x.install(SimpleNamespace(app=self.app))
        self.client = self.app.test_client()

    def test_native_data_keeps_real_content_and_removes_media_link(self):
        data = x._normalize(RAW, expected=RAW['id_str'])
        self.assertEqual(data['text'], 'A real post')
        self.assertEqual(data['media'][0]['height'], 1200)
        self.assertEqual(data['url'], 'https://x.com/test/status/'+RAW['id_str'])
        self.assertNotIn('favorite_count', data)

    def test_source_id_and_media_urls_fail_closed(self):
        self.assertIsNone(x._normalize(RAW, expected='54321'))
        for url in ['javascript:alert(1)', 'https://pbs.twimg.com.evil.test/a',
                    'https://user:pass@pbs.twimg.com/a', 'https://pbs.twimg.com:8443/a', 'http://pbs.twimg.com/a']:
            self.assertEqual(x._image(url), '')
        self.assertIsNone(x._normalize({'__typename': 'TweetTombstone'}))

    def test_id_input_never_becomes_an_outbound_url(self):
        with patch.object(x, '_fetch') as fetch:
            self.assertEqual(self.client.get('/api/x-post/not-a-number').status_code, 400)
            fetch.assert_not_called()

    def test_cache_avoids_repeated_fetches(self):
        with patch.object(x, '_fetch', return_value=x._normalize(RAW)) as fetch:
            for _ in range(2):
                response = self.client.get('/api/x-post/'+RAW['id_str'])
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json['ok'])
            self.assertEqual(fetch.call_count, 1)

    def test_upstream_failure_is_cached_and_retryable(self):
        with patch.object(x, '_fetch', side_effect=x.requests.Timeout) as fetch:
            for _ in range(2):
                response = self.client.get('/api/x-post/'+RAW['id_str'])
                self.assertEqual(response.status_code, 503)
                self.assertFalse(response.json['ok'])
            self.assertEqual(fetch.call_count, 1)

    def test_cache_is_bounded(self):
        with patch.object(x, '_fetch', return_value=None):
            for tid in range(10000, 10300):
                x._preview(str(tid))
        self.assertEqual(len(x._CACHE), 256)

if __name__ == '__main__':
    unittest.main()
