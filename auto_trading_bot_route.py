"""Dedicated Auto Trading Bot route.

This module gives the autonomous bot one stable destination and fixes every
navigation-style "Start Trading" CTA to use it. The actual bot start/stop
button on the bot page is deliberately excluded.
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import requests
from flask import redirect, jsonify


def install(dashboard):
    app = dashboard.app
    if getattr(app, '_orca_auto_trading_route_installed', False):
        return
    app._orca_auto_trading_route_installed = True

    # Public BTC/ETH/SOL USD quotes. One backend call for all three Home cards;
    # short shared cache avoids three upstream calls per user every refresh.
    _home_quote_cache = {'at': 0.0, 'quotes': {}, 'attempt': 0.0, 'opens': {}, 'busy': False}
    _home_quote_lock = threading.Lock()

    def major_quote_snapshot():
        now = time.monotonic()
        with _home_quote_lock:
            quotes = _home_quote_cache['quotes']
            if quotes and now - _home_quote_cache['at'] < 1:
                return {'ok': True, 'prices': dict(quotes), 'stale': False}
            # Do not pound the provider during a temporary upstream outage.
            if _home_quote_cache['busy'] or now - _home_quote_cache['attempt'] < 1:
                return {'ok': bool(quotes), 'prices': dict(quotes), 'stale': True}
            _home_quote_cache['attempt'] = now
            _home_quote_cache['busy'] = True

        def read_quote(symbol):
            headers = {'Accept': 'application/json', 'User-Agent': 'OrcAgent/1.0'}
            url = 'https://api.exchange.coinbase.com/products/' + symbol + '-USD/'
            with _home_quote_lock:
                opened_hit = _home_quote_cache['opens'].get(symbol)
            if not opened_hit or now - opened_hit[0] >= 60:
                response = requests.get(url + 'stats', headers=headers, timeout=2)
                response.raise_for_status()
                opened = float(response.json()['open'])
                if not (0 < opened < 1e9):
                    raise ValueError('Invalid exchange open')
                with _home_quote_lock:
                    _home_quote_cache['opens'][symbol] = (now, opened)
            else:
                opened = opened_hit[1]
            response = requests.get(url + 'ticker', headers=headers, timeout=2)
            response.raise_for_status()
            data = response.json()
            last = float(data['price'])
            if not (0 < last < 1e9):
                raise ValueError('Invalid exchange quote')
            return symbol, {'price': last, 'observed_at': time.time(),
                            'change24h': round((last / opened - 1) * 100, 2)}

        fresh = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(read_quote, name) for name in ('BTC', 'ETH', 'SOL')]
            for future in futures:
                try:
                    symbol, quote = future.result()
                    fresh[symbol] = quote
                except (requests.RequestException, ValueError, KeyError,
                        TypeError, OverflowError):
                    pass
        with _home_quote_lock:
            if fresh:
                _home_quote_cache['quotes'] = {
                    **_home_quote_cache['quotes'], **fresh}
                _home_quote_cache['at'] = time.monotonic()
            quotes = dict(_home_quote_cache['quotes'])
            _home_quote_cache['busy'] = False
        return {'ok': bool(quotes), 'prices': quotes, 'stale': not bool(fresh)}

    dashboard._major_quote_snapshot = major_quote_snapshot

    @app.route('/api/home/major-prices')
    def home_major_prices():
        response = jsonify(major_quote_snapshot())
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/auto-trading-bot')
    def auto_trading_bot_page():
        # One bot page: the same view the menu's /bot renders.
        return dashboard.bot_overview_page()

    @app.after_request
    def _fix_start_trading_links(response):
        ctype = response.headers.get('Content-Type', '')
        if response.status_code != 200 or 'text/html' not in ctype:
            return response
        try:
            body = response.get_data(as_text=True)
        except Exception:
            return response

        original = body

        # Rewrite every known home/hero version at the HTML boundary. This is
        # intentionally server-side so an old cached home-mobile/home-desktop
        # bundle cannot decide that Start Trading means Live Market.
        replacements = (
            ('href="/bot?view=trading"', 'href="/auto-trading-bot"'),
            ("href='/bot?view=trading'", "href='/auto-trading-bot'"),
            ('<a class="oa-home-primary" href="/live-market">Start Trading',
             '<a class="oa-home-primary" href="/auto-trading-bot">Start Trading'),
            ('<a class="oa-m-primary" href="/live-market">Start Trading',
             '<a class="oa-m-primary" href="/auto-trading-bot">Start Trading'),
            ('<a class="hero-cta" href="/live-market"',
             '<a class="hero-cta" href="/auto-trading-bot"'),
        )
        for old, new in replacements:
            body = body.replace(old, new)

        # This guard is injected into <head>, before navbar.js/home-mobile.js
        # can run. It therefore wins even if Safari/PWA still has an old home
        # bundle that creates a /live-market Start Trading anchor later.
        # Capture phase is deliberate: stop the old target before any bubble
        # handler or SPA navigation controller sees the tap.
        #
        # A same-origin <script src>, not an inline block: this hook installs
        # before security_hardening.py in app_entry.py, and Flask runs
        # after_request hooks in REVERSE install() order, so an inline
        # script appended here would run after security_hardening's CSP
        # nonce-injection pass already completed -- it would never get a
        # nonce and CSP would silently drop the whole guard. See
        # static/auto-bot-route-guard.js for the full explanation.
        guard = '<script src="/static/auto-bot-route-guard.js?v=2" id="oa-auto-bot-route-guard"></script>'
        if 'id="oa-auto-bot-route-guard"' not in body:
            if '<head>' in body:
                body = body.replace('<head>', '<head>\n' + guard, 1)
            elif '</body>' in body:
                body = body.replace('</body>', guard + '\n</body>', 1)
            else:
                body = guard + body

        if body != original:
            response.set_data(body)
            response.headers['Content-Length'] = str(len(response.get_data()))

        # HTML must never pin an obsolete navigation bundle in an installed
        # iOS web app. Static assets can still be cached by their own versions.
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
