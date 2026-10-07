"""A page the browser navigates to never shows a bare JSON error.

The API answers errors as JSON, and so do the security layers that run
before any route: the global rate limit, CSRF and authorization guards.
For a fetch from the app that is right. But when the request is the page
itself -- someone opens /wallet, taps a link, reloads -- the browser showed
the raw text {"error":"Too many requests"} on a white screen.

For such a navigation this swaps the JSON for a small OrcAgent page with
the same status code. A 429 says "one moment" and reloads itself after a
few seconds; anything else offers a way back Home. Everything it needs is
inline, so it looks right even when nothing else can be loaded.
"""
from __future__ import annotations

from flask import request

RETRY_SECONDS = 5

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a0b0e">
%(refresh)s<title>%(title)s · OrcAgent</title>
<style>
html,body{margin:0;height:100%%;background:#0a0b0e;color:#eef1f5;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
main{min-height:100%%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:24px;box-sizing:border-box;text-align:center}
.mark{width:56px;height:56px;border-radius:16px;background:#f7b955;display:flex;align-items:center;justify-content:center}
h1{margin:4px 0 0;font-size:22px;font-weight:700}
p{margin:0;max-width:320px;font-size:15px;line-height:1.5;color:#a0a7b1}
a{display:inline-block;margin-top:8px;padding:12px 22px;border-radius:12px;background:#f7b955;color:#0a0b0e;font-weight:700;text-decoration:none}
.spin{width:22px;height:22px;border-radius:50%%;border:3px solid #2a2f37;border-top-color:#f7b955;animation:s 0.9s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none}}
</style>
</head>
<body>
<main>
<div class="mark"><svg width="24" height="22" viewBox="0 0 22 20" aria-hidden="true"><path d="M11 0 22 20H0z" fill="#0a0b0e"/></svg></div>
<h1>%(title)s</h1>
<p>%(text)s</p>
%(action)s
</main>
</body>
</html>
"""


def is_page_navigation():
    """The browser is loading a page, not the app fetching data."""
    if request.method != 'GET' or request.path.startswith('/api/'):
        return False
    dest = request.headers.get('Sec-Fetch-Dest')
    if dest:
        return dest in ('document', 'iframe')
    return 'text/html' in (request.headers.get('Accept') or '')


def page(status):
    if status == 429:
        return _PAGE % {
            'refresh': '<meta http-equiv="refresh" content="%d">\n' % RETRY_SECONDS,
            'title': 'One moment',
            'text': 'OrcAgent is busy for a second. This page reloads by itself.',
            'action': '<div class="spin" role="status" aria-label="Reloading"></div>',
        }
    if status in (401, 403):
        title, text = 'You can’t open this page', 'You may need to sign in again, or this page isn’t available to your account.'
    elif status == 404:
        title, text = 'Page not found', 'This page doesn’t exist or has moved.'
    else:
        title, text = 'Something went wrong', 'Please try again in a moment.'
    return _PAGE % {'refresh': '', 'title': title, 'text': text,
                    'action': '<a href="/">Back to Home</a>'}


def install(d):
    app = d.app
    if getattr(app, '_orca_friendly_errors_installed', False):
        return
    app._orca_friendly_errors_installed = True

    @app.after_request
    def _friendly_error_page(response):
        if (response.status_code >= 400 and response.mimetype == 'application/json'
                and is_page_navigation()):
            response.set_data(page(response.status_code))
            response.mimetype = 'text/html'
            response.headers['Cache-Control'] = 'no-store'
            if response.status_code == 429:
                response.headers.setdefault('Retry-After', str(RETRY_SECONDS))
        return response
