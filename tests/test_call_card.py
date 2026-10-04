"""Recorded prices and guarded logo handling on public share cards."""
import io
import unittest
from unittest.mock import Mock
from PIL import Image
import call_invitations as inv


class CallCard(unittest.TestCase):
    def test_small_prices_are_readable_and_invalid_prices_are_unavailable(self):
        for value, expected in [(0.0000188, '$0.0000188'), (0.00000001, '$0.00000001'),
                                (145.25, '$145.25'), (1234, '$1,234'),
                                (1e-19, '< $0.000000000000000001')]:
            with self.subTest(value=value):
                self.assertEqual(inv.format_card_price(value), expected)
        for value in [None, 'invalid', 0, -1, float('nan'), float('inf')]:
            self.assertEqual(inv.format_card_price(value), 'Unavailable')

    def test_logo_uses_existing_guard_and_caches_failure(self):
        inv._card_logo.cache_clear()
        d = Mock()
        d._safe_external_image_url.return_value = False
        self.assertIsNone(inv._card_logo(d, 'https://127.0.0.1/logo.png', 1))
        self.assertIsNone(inv._card_logo(d, 'https://127.0.0.1/logo.png', 1))
        d._safe_external_image_url.assert_called_once()
        d.requests.get.assert_not_called()
        self.assertIsNone(inv._card_logo(d, 'http://example.com/logo.png', 1))
        d.requests.get.assert_not_called()

    def test_png_renders_logo_and_long_text_without_changing_recorded_data(self):
        call = dict(id=79, mint='So11111111111111111111111111111111111111112',
                    symbol='ATTENTION ' * 30, token_name='Attention Inu ' * 30,
                    username='degentrader1990 ' * 30, is_verified=1,
                    price_at_call=0.0000188, timestamp='2026-10-04 08:23:48',
                    note='A long token analysis ' * 100)
        before = dict(call)
        fallback = Image.open(io.BytesIO(inv.render_card(call)))
        logo = Image.new('RGB', (300,100), '#ff0033')
        with_logo = Image.open(io.BytesIO(inv.render_card(call, {'username':'another trader '*30}, logo)))
        self.assertEqual(with_logo.size, (1200,630))
        self.assertEqual(fallback.size, (1200,630))
        self.assertEqual(with_logo.getpixel((100,190)), (255,0,51))
        self.assertNotEqual(fallback.getpixel((100,190)), (255,0,51))
        self.assertEqual(call, before)


if __name__ == '__main__':
    unittest.main()
