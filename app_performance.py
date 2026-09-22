"""Shared performance bootstrap for every OrcAgent HTML page.

Loads route-critical styles before first paint and keeps page-specific scripts
deferred. The browser should never render legacy markup and restyle it later.
"""


def install(appmod) -> None:
    if getattr(appmod, '_app_performance_installed', False):
        return
    appmod._app_performance_installed = True

    @appmod.app.after_request
    def _inject_performance_assets(response):
        try:
            if response.status_code != 200:
                return response
            ctype = (response.content_type or '').lower()
            if 'text/html' not in ctype or appmod.request.method not in ('GET', 'HEAD'):
                return response
            html = response.get_data(as_text=True)
            if '</head>' not in html:
                return response
            path = appmod.request.path.rstrip('/') or '/'
            tags = []

            def style(asset, href, extra=''):
                if asset not in html:
                    tags.append(f'<link rel="stylesheet" href="{href}"{extra}>')

            def script(asset, src, extra=''):
                if asset not in html:
                    tags.append(f'<script src="{src}" defer{extra}></script>')

            if 'data-orca-bfcache-guard="1"' not in html:
                tags.append(
                    '<script data-orca-bfcache-guard="1">'
                    '(function(){window.addEventListener("pageshow",function(e){'
                    'if(!e.persisted)return;e.stopImmediatePropagation();'
                    'setTimeout(function(){document.dispatchEvent(new CustomEvent("orca:bfcache-restored"));},0);'
                    '},true);})();'
                    '</script>'
                )

            style('app-ux.css', '/static/app-ux.css?v=5', ' id="oa-app-ux-css"')
            script('app-ux.js', '/static/app-ux.js?v=4', ' id="oa-app-ux-js"')
            style('shared-trade-card-v2.css', '/static/shared-trade-card-v2.css?v=1', ' id="oa-shared-trade-card-css"')
            script('shared-trade-card-v2.js', '/static/shared-trade-card-v2.js?v=1', ' id="oa-shared-trade-card-js"')
            style('feed-action-icons.css', '/static/feed-action-icons.css?v=2')
            script('feed-action-icons.js', '/static/feed-action-icons.js?v=3')

            if 'fonts.googleapis.com' in html and 'rel="preconnect" href="https://fonts.googleapis.com"' not in html:
                tags.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
                tags.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')

            if path == '/wallet':
                style('portfolio-redesign.css', '/static/portfolio-redesign.css?v=6')
                # v8 removes all legacy activity/history cards from Portfolio.
                # The only trade list left on this route is the dedicated,
                # Live-Market-only transaction component.
                script('portfolio-redesign.js', '/static/portfolio-redesign.js?v=9')
                script('portfolio-assets.js', '/static/portfolio-assets.js?v=1')
            elif path == '/live-market':
                style('live-market-redesign.css', '/static/live-market-redesign.css?v=7')
                style('live-market-final.css', '/static/live-market-final.css?v=4', ' data-oa-live-final="1"')
                script('live-market-redesign.js', '/static/live-market-redesign.js?v=5')
                script('live-market-hotfix.js', '/static/live-market-hotfix.js?v=8', ' data-oa-live-hotfix="1"')
            elif path == '/groups':
                style('groups-redesign.css', '/static/groups-redesign.css?v=1')
                script('groups-redesign.js', '/static/groups-redesign.js?v=1')
            elif path == '/':
                style('home-mobile.css', '/static/home-mobile.css?v=8', ' media="(max-width:768px)"')
                style('home-mobile-polish.css', '/static/home-mobile-polish.css?v=6', ' media="(max-width:768px)"')
                style('home-composer-mobile.css', '/static/home-composer-mobile.css?v=1', ' media="(max-width:768px)"')
                style('home-desktop.css', '/static/home-desktop.css?v=1', ' media="(min-width:1025px)"')

            # Chromium/Android uses document.documentElement as the root
            # scrollingElement in standards mode. The previous hotfix made body
            # the scroll owner while html stayed overflow:hidden; that can still
            # leave Android with a locked root scroller even though iOS happens
            # to tolerate the body scroller. Keep exactly ONE vertical scroll
            # owner, but make it the real standards-mode root: html. Body and the
            # app shells are allowed to grow naturally and never become nested
            # vertical scrollers.
            # Use the standards-mode root scroller on every ordinary mobile
            # document page. Previously this was limited to Home + Portfolio,
            # so Android Chrome/WebView still ended up with body/inner-container
            # scrolling on Bot, Profile, Notifications, Groups, Settings, etc.
            # iOS is permissive about that split ownership; Chromium is not.
            # Android must use the exact same root document scroller as iOS;
            # never replace it with an Android-only #main-content scroller.
            # Messages and Live Market intentionally own fullscreen/internal
            # scrollers (including nested /messages/<wallet> routes), so those
            # route families remain excluded.
            _root_scroll_excluded_prefixes = ('/messages', '/live-market')
            _uses_internal_mobile_scroller = any(
                path == prefix or path.startswith(prefix + '/')
                for prefix in _root_scroll_excluded_prefixes
            )
            if not _uses_internal_mobile_scroller and 'data-oa-native-mobile-scroll="1"' not in html:
                tags.append(
                    '<script data-oa-native-mobile-scroll="1">'
                    '(function(){if(window.matchMedia&&window.matchMedia("(max-width:768px)").matches){'
                    'document.documentElement.classList.add("oa-native-mobile-scroll");'
                    '}})();'
                    '</script>'
                )
                tags.append(
                    '<style data-oa-native-mobile-scroll-css="1">'
                    '@media(max-width:768px){'
                    'html.oa-native-mobile-scroll{height:auto!important;min-height:100%!important;max-height:none!important;'
                    'overflow-x:hidden!important;overflow-y:auto!important;-webkit-overflow-scrolling:touch!important;'
                    'overscroll-behavior-y:none!important;touch-action:pan-y!important}'
                    'html.oa-native-mobile-scroll body{height:auto!important;min-height:100dvh!important;max-height:none!important;'
                    'overflow:visible!important;position:static!important;touch-action:pan-y!important}'
                    'html.oa-native-mobile-scroll body #app{height:auto!important;min-height:100dvh!important;max-height:none!important;'
                    'overflow:visible!important;position:static!important}'
                    'html.oa-native-mobile-scroll body .app-body,'
                    'html.oa-native-mobile-scroll body .wrap,'
                    'html.oa-native-mobile-scroll body .wlt-center,'
                    'html.oa-native-mobile-scroll body .wlt-content{height:auto!important;min-height:0!important;max-height:none!important;overflow:visible!important}'
                    'html.oa-native-mobile-scroll.oa-modal-open,'
                    'html.oa-native-mobile-scroll.oa-wallet-actions-open,'
                    'html.oa-native-mobile-scroll.oa-app-menu-open{overflow:hidden!important}'

                    '}'
                    '</style>'
                )

            if tags:
                html = html.replace('</head>', '\n'.join(tags) + '\n</head>', 1)
                response.set_data(html)
                response.headers['Content-Length'] = str(len(response.get_data()))
        except Exception as exc:
            print(f'[performance] asset injection skipped: {exc}', flush=True)
        return response
