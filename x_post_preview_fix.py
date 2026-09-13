"""Ensure X/Open Graph previews for /post/<id> use the actual OrcAgent card.

For trade/chart feed posts, replace every existing OG/Twitter tag with one
authoritative metadata set that points at OrcAgent's real 1200x630 card
renderer. When an X cache-bust query (xv) is present, keep that version in the
canonical/og:url and the image URL too. X may otherwise normalize the shared
URL back to the old canonical URL and reuse the stale generic preview.
"""
import html
import re

_INSTALLED = False
_POST_ID_RE = re.compile(r'^[pt]\d+$')
_SOCIAL_META_RE = re.compile(
    r'\s*<meta\s+(?:name|property)=["\'](?:twitter:[^"\']+|og:[^"\']+)["\'][^>]*>\s*',
    re.IGNORECASE,
)
_CANONICAL_RE = re.compile(
    r'\s*<link\s+rel=["\']canonical["\'][^>]*>\s*',
    re.IGNORECASE,
)


def _safe_version(value):
    value = str(value or '').strip()
    return value if re.fullmatch(r'[A-Za-z0-9_-]{1,24}', value) else ''


def _social_block(base, post_id, tc, version=''):
    safe_id = html.escape(post_id, quote=True)
    version = _safe_version(version)
    suffix = ('?xv=' + version) if version else ''
    canonical = f'{base}/post/{safe_id}{suffix}'
    image_version = version or '6'
    image = f'{base}/api/trade-card/{safe_id}.png?v={html.escape(image_version, quote=True)}'

    symbol = html.escape(str((tc or {}).get('symbol') or 'TOKEN'), quote=True)
    if (tc or {}).get('kind') == 'chart':
        title = f'${symbol} on OrcAgent'
        chg = float((tc or {}).get('chg24h') or 0)
        sign = '+' if chg >= 0 else ''
        desc = f'{sign}{chg:.2f}% (24h) · View on OrcAgent'
    else:
        title = f'${symbol} trade on OrcAgent'
        pnl = float((tc or {}).get('pnl_pct') or 0)
        sign = '+' if pnl >= 0 else ''
        desc = f'{sign}{pnl:.2f}% · View on OrcAgent'

    title = html.escape(title, quote=True)
    desc = html.escape(desc, quote=True)
    return f'''\n<!-- authoritative OrcAgent X preview -->
<link rel="canonical" href="{canonical}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:description" content="{desc}">
<meta name="twitter:image" content="{image}">
<meta name="twitter:image:alt" content="{title}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="OrcAgent">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{image}">
<meta property="og:image:secure_url" content="{image}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
'''


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = dashboard_module.app

    @app.after_request
    def _fix_x_post_preview(response):
        try:
            from flask import request
            path = request.path or ''
            if response.status_code != 200 or response.mimetype != 'text/html':
                return response
            if not path.startswith('/post/'):
                return response
            post_id = path[len('/post/'):]
            if not _POST_ID_RE.fullmatch(post_id or ''):
                return response

            tc = dashboard_module._tc_lookup(post_id)
            if not tc:
                return response

            body = response.get_data(as_text=True)
            if '<head' not in body.lower():
                return response

            body = _SOCIAL_META_RE.sub('\n', body)
            body = _CANONICAL_RE.sub('\n', body)
            block = _social_block(
                'https://orcagent.fun',
                post_id,
                tc,
                request.args.get('xv', ''),
            )
            body, count = re.subn(
                r'(<head\b[^>]*>)',
                lambda m: m.group(1) + block,
                body,
                count=1,
                flags=re.IGNORECASE,
            )
            if count:
                response.set_data(body)
                response.content_length = len(response.get_data())
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = '0'
        except Exception as exc:
            app.logger.warning('X post preview fix skipped: %s', exc)
        return response
