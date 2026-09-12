"""Shared performance bootstrap for every OrcAgent HTML page.

Keeps the common UX layer early in the document instead of waiting for a
page-specific loader, and preloads the heaviest route assets that otherwise
create a visible blank/styled-late interval on mobile.
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
            if 'text/html' not in ctype:
                return response
            if appmod.request.method not in ('GET', 'HEAD'):
                return response

            html = response.get_data(as_text=True)
            if '</head>' not in html:
                return response

            path = appmod.request.path.rstrip('/') or '/'
            tags = []

            # Shared layer first, on every HTML screen. page-loader.js has ID
            # guards, so older templates that still load it won't duplicate it.
            if 'id="oa-app-ux-css"' not in html:
                tags.append('<link id="oa-app-ux-css" rel="stylesheet" href="/static/app-ux.css?v=3">')
            if 'id="oa-app-ux-js"' not in html:
                tags.append('<script id="oa-app-ux-js" src="/static/app-ux.js?v=3" defer></script>')

            # The persistent mobile nav is loaded here with a cache-busted URL
            # as well as by navbar.js. Its build guard makes this idempotent,
            # while this early tag guarantees users immediately get the new
            # Home / Live Market / Post / Portfolio / Menu route after deploy.
            tags.append('<script src="/static/mobile-bottom-nav.js?v=5" defer></script>')

            # Font DNS/TLS setup costs are otherwise paid during first paint.
            if 'fonts.googleapis.com' in html and 'rel="preconnect" href="https://fonts.googleapis.com"' not in html:
                tags.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
                tags.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')

            # These redesigns are dynamically appended by navbar.js. Preload
            # the exact same URL so Safari can fetch them in parallel with the
            # document instead of only after navbar.js executes.
            if path == '/wallet':
                tags.extend([
                    '<link rel="preload" href="/static/portfolio-redesign.css?v=4" as="style">',
                    '<link rel="preload" href="/static/portfolio-redesign.js?v=4" as="script">',
                    '<link rel="preload" href="/static/portfolio-assets.js?v=1" as="script">',
                ])
            elif path == '/live-market':
                tags.extend([
                    '<link rel="preload" href="/static/live-market-redesign.css?v=7" as="style">',
                    '<link rel="preload" href="/static/live-market-redesign.js?v=5" as="script">',
                ])
            elif path == '/':
                # Mobile Home is now feed-first. Load the cache-busted controller
                # directly so the composer is in place on first paint. The
                # controller is guarded against a second load from navbar.js.
                tags.extend([
                    '<link rel="preload" href="/static/home-mobile.css?v=4" as="style" media="(max-width:767px)">',
                    '<link rel="stylesheet" href="/static/home-social-feed.css?v=1" media="(max-width:767px)">',
                    '<script src="/static/home-mobile.js?v=4" defer></script>',
                    '<link rel="preload" href="/static/home-desktop.css?v=1" as="style" media="(min-width:1025px)">',
                ])

            if tags:
                html = html.replace('</head>', '\n'.join(tags) + '\n</head>', 1)
                response.set_data(html)
                response.headers['Content-Length'] = str(len(response.get_data()))
        except Exception as exc:
            print(f'[performance] asset injection skipped: {exc}', flush=True)
        return response
