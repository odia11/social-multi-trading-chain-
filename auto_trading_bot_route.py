"""Dedicated Auto Trading Bot route.

This exists so Start Trading has one stable, query-free destination that cannot
be confused with Live Market or have its query string stripped by iOS/PWA
navigation. It reuses the existing bot APIs and security/session helpers.
"""
import sqlite3
from flask import redirect


def install(dashboard):
    app = dashboard.app

    @app.route('/auto-trading-bot')
    def auto_trading_bot_page():
        dashboard._log_readonly_attempt()
        wallet = dashboard._authenticated_wallet()
        if not wallet:
            return redirect('/')

        conn = sqlite3.connect(dashboard.DB_FILE)
        try:
            row = conn.execute(
                'SELECT narrative_agent_enabled, tiered_tp_enabled FROM users WHERE wallet_address=?',
                (wallet,),
            ).fetchone()
        finally:
            conn.close()

        narrative_agent_enabled = bool(row[0]) if row else False
        tiered_tp_enabled = bool(row[1]) if row else False

        return dashboard._render_no_cache(
            'auto_trading_bot.html',
            wallet=wallet,
            wallet_short=(wallet[:4] + '...' + wallet[-4:]) if len(wallet) >= 8 else wallet,
            is_admin=dashboard._is_owner(wallet),
            csrf_token=dashboard._get_csrf_token(),
            narrative_agent_enabled=narrative_agent_enabled,
            tiered_tp_enabled=tiered_tp_enabled,
            tp1_multiple=dashboard.TP1_MULTIPLE,
            tp1_sell_fraction=int(dashboard.TP1_SELL_FRACTION * 100),
            trailing_stop_pct=int(dashboard.TRAILING_STOP_PCT * 100),
        )

    @app.after_request
    def _fix_start_trading_links(response):
        """Route every product-level Start Trading CTA to the dedicated bot page.

        This intentionally targets only the known hero CTA patterns, not all
        /live-market links, because Live Market itself remains a valid manual
        trading destination elsewhere in the product.
        """
        ctype = response.headers.get('Content-Type', '')
        if 'text/html' not in ctype:
            return response
        try:
            body = response.get_data(as_text=True)
        except Exception:
            return response

        original = body
        body = body.replace('href="/bot?view=trading"', 'href="/auto-trading-bot"')
        body = body.replace("href='/bot?view=trading'", "href='/auto-trading-bot'")
        body = body.replace(
            '<a class="oa-home-primary" href="/live-market">Start Trading',
            '<a class="oa-home-primary" href="/auto-trading-bot">Start Trading',
        )
        body = body.replace(
            '<a class="hero-cta" href="/live-market"',
            '<a class="hero-cta" href="/auto-trading-bot"',
        )

        if body != original:
            response.set_data(body)
            response.headers['Content-Length'] = str(len(response.get_data()))
        return response
