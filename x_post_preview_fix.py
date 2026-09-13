"""Ensure X/Open Graph previews for /post/<id> use the actual OrcAgent card.

The built-in post permalink emits generic/fallback social metadata for normal
feed posts. For posts that contain a __TRADE__ or __CHART__ embed, replace all
existing OG/Twitter tags with one authoritative set pointing at the existing
/api/trade-card/<id>.png renderer. This avoids duplicate metadata and stops X
from choosing the generic OrcAgent image instead of the token/trade card.
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


def _social_block(base, post_id, tc):
    safe_id = html.escape(post_id, quote=True)
    canonical = f'{base}/post/{safe_id}'
    # Query version deliberately changes the crawler image URL after this fix,
    # preventing X from reusing the previously cached generic preview image.
    image = f'{base}/api/trade-card/{safe_id}.png?v=3'
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

            # Only replace metadata for actual trade/chart cards. Plain text and
            # photo posts keep the original permalink metadata unchanged.
            tc = dashboard_module._tc_lookup(post_id)
            if not tc:
                return response

            body = response.get_data(as_text=True)
            if '<head' not in body.lower():
                return response

            body = _SOCIAL_META_RE.sub('\n', body)
            body = _CANONICAL_RE.sub('\n', body)
            base = 'https://orcagent.fun'
            block = _social_block(base, post_id, tc)
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
        except Exception as exc:
            app.logger.warning('X post preview fix skipped: %s', exc)
        return response
