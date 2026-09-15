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

            style('app-ux.css', '/static/app-ux.css?v=3', ' id="oa-app-ux-css"')
            script('app-ux.js', '/static/app-ux.js?v=3', ' id="oa-app-ux-js"')
            style('shared-trade-card-v2.css', '/static/shared-trade-card-v2.css?v=1', ' id="oa-shared-trade-card-css"')
            script('shared-trade-card-v2.js', '/static/shared-trade-card-v2.js?v=1', ' id="oa-shared-trade-card-js"')
            style('feed-action-icons.css', '/static/feed-action-icons.css?v=2')
            script('feed-action-icons.js', '/static/feed-action-icons.js?v=1')

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
                style('home-mobile.css', '/static/home-mobile.css?v=6', ' media="(max-width:767px)"')
                style('home-mobile-polish.css', '/static/home-mobile-polish.css?v=5', ' media="(max-width:767px)"')
                style('home-composer-mobile.css', '/static/home-composer-mobile.css?v=1', ' media="(max-width:767px)"')
                style('home-desktop.css', '/static/home-desktop.css?v=1', ' media="(min-width:1025px)"')

            # Android/Chromium is much less forgiving than iOS Safari when both
            # html and body are made independent overflow scrollers. The legacy
            # dashboard starts with html,body and #app locked to 100dvh +
            # overflow:hidden, while the route CSS previously changed BOTH html
            # and body to overflow-y:auto. On Android that can leave no stable
            # scroll owner (or only a tiny edge area that accepts the gesture).
            #
            # For the document-style mobile routes, make body the one and only
            # native vertical scroller. This is injected last so it wins over
            # the old route CSS without relying on :has(), JS timing, or browser
            # sniffing. Modal/search body overflow locks continue to work because
            # they lock the actual scroll container.
            if path in ('/', '/wallet') and 'data-oa-native-mobile-scroll="1"' not in html:
                tags.append(
                    '<script data-oa-native-mobile-scroll="1">'
                    '(function(){if(window.matchMedia&&window.matchMedia("(max-width:767px)").matches)'
                    'document.documentElement.classList.add("oa-native-mobile-scroll");})();'
                    '</script>'
                )
                tags.append(
                    '<style data-oa-native-mobile-scroll-css="1">'
                    '@media(max-width:767px){'
                    'html.oa-native-mobile-scroll{height:100%!important;min-height:100%!important;'
                    'overflow:hidden!important;overscroll-behavior-y:none!important;touch-action:pan-y!important}'
                    'html.oa-native-mobile-scroll body{height:100dvh!important;min-height:100dvh!important;max-height:100dvh!important;'
                    'overflow-x:hidden!important;overflow-y:auto!important;position:static!important;'
                    '-webkit-overflow-scrolling:touch!important;overscroll-behavior-y:none!important;touch-action:pan-y!important}'
                    'html.oa-native-mobile-scroll body #app{height:auto!important;min-height:100%!important;max-height:none!important;'
                    'overflow:visible!important;position:static!important}'
                    'html.oa-native-mobile-scroll body .app-body,'
                    'html.oa-native-mobile-scroll body .wrap,'
                    'html.oa-native-mobile-scroll body .wlt-center,'
                    'html.oa-native-mobile-scroll body .wlt-content{height:auto!important;max-height:none!important;overflow:visible!important}'
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
