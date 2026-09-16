"""Dedicated Auto Trading Bot route.

This module gives the autonomous bot one stable destination and fixes every
navigation-style "Start Trading" CTA to use it. The actual bot start/stop
button on the bot page is deliberately excluded.
"""
import sqlite3
from flask import g, redirect


def install(dashboard):
    app = dashboard.app
    if getattr(app, '_orca_auto_trading_route_installed', False):
        return
    app._orca_auto_trading_route_installed = True

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
        # This module's after_request hook is registered before
        # security_hardening's, so by Flask's LIFO after_request order it
        # runs AFTER security_hardening has already handed out nonces to the
        # script tags that existed at that point -- a plain <script> injected
        # here would be silently dropped by the CSP's script-src-elem nonce
        # requirement. Reading the same per-request nonce security_hardening
        # put in g sidesteps the ordering entirely.
        _nonce = getattr(g, 'orca_csp_nonce', '')
        _nonce_attr = f' nonce="{_nonce}"' if _nonce else ''
        guard = '<script' + _nonce_attr + r''' id="oa-auto-bot-route-guard">
(function(){
  var TARGET='/auto-trading-bot';
  function label(el){return String((el&&el.textContent)||'').replace(/\s+/g,' ').trim().toLowerCase();}
  function isBotToggle(el){
    return !!(el && (el.id==='bot-toggle-btn' || el.id==='sb-start-btn' ||
      (el.closest && el.closest('#bot-dashboard,.status-card'))));
  }
  function isStartNavigation(el){
    if(!el || isBotToggle(el)) return false;
    if(el.id==='bot-start-landing' || el.id==='oa-home-bot-btn' || el.id==='mn-drawer-trade-btn') return true;
    if(el.classList && (el.classList.contains('oa-home-primary') ||
       el.classList.contains('oa-m-primary') || el.classList.contains('hero-cta'))) return true;
    var t=label(el);
    return t==='start trading' || t.indexOf('start trading →')===0 || t.indexOf('start trading ➜')===0;
  }
  document.addEventListener('click',function(e){
    var el=e.target&&e.target.closest?e.target.closest('a,button'):null;
    if(!isStartNavigation(el)) return;
    e.preventDefault();
    e.stopPropagation();
    if(e.stopImmediatePropagation) e.stopImmediatePropagation();
    window.location.href=TARGET;
  },true);
  document.addEventListener('touchend',function(e){
    var el=e.target&&e.target.closest?e.target.closest('a,button'):null;
    if(!isStartNavigation(el)) return;
    e.preventDefault();
    e.stopPropagation();
    if(e.stopImmediatePropagation) e.stopImmediatePropagation();
    window.location.href=TARGET;
  },{capture:true,passive:false});
})();
</script>'''
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
