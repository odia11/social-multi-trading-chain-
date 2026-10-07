"""Ensure X/Open Graph previews for /post/<id> use the actual OrcAgent visual.

Trade/chart posts use the existing 1200x630 server renderer. Feed posts whose
visual is stored as an image_url data URI now get a public image endpoint so X
can fetch the exact image instead of falling back to OrcAgent's generic site
card. Cache-bust versions are kept in canonical and image URLs so X re-crawls.
"""
import base64
import hashlib
import html
import io
import os
import re
import sqlite3

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
_AGENT_IMAGE_RE = re.compile(r'^/media/agent/([0-9a-f]{40}\.webp)$')
X_CARD = (1200, 630)
_card_cache = {}
_DATA_URI_RE = re.compile(r'^data:(image/(?:png|jpeg|jpg|webp|gif));base64,(.+)$', re.IGNORECASE | re.DOTALL)


def _safe_version(value):
    value = str(value or '').strip()
    return value if re.fullmatch(r'[A-Za-z0-9_-]{1,24}', value) else ''


def _feed_image(dashboard_module, post_id):
    """The post's own picture as (mime, bytes): an uploaded photo (stored as a
    data URI) or a picture @orcagent drew (/media/agent/<hash>.webp)."""
    if not post_id.startswith('p') or not post_id[1:].isdigit():
        return None
    conn = sqlite3.connect(dashboard_module.DB_FILE)
    try:
        row = conn.execute('SELECT image_url FROM feed_posts WHERE id=? LIMIT 1', (post_id[1:],)).fetchone()
    finally:
        conn.close()
    raw = (row[0] if row else '') or ''
    m = _DATA_URI_RE.match(raw)
    if m:
        mime = m.group(1).lower().replace('image/jpg', 'image/jpeg')
        try:
            data = base64.b64decode(m.group(2), validate=False)
        except Exception:
            return None
    else:
        a = _AGENT_IMAGE_RE.match(raw)
        if not a:
            return None
        try:
            import agent_post_images
            path = os.path.join(agent_post_images.media_dir(dashboard_module), a.group(1))
            with open(path, 'rb') as f:
                data = f.read()
        except Exception:
            return None
        mime = 'image/webp'
    if not data or len(data) > 8 * 1024 * 1024:
        return None
    return mime, data


def _x_card(data):
    """The post's picture as the 1200x630 JPEG X shows: the whole picture,
    fitted, on a blurred and darkened copy of itself. Square and portrait
    photos used to be declared 1200x630 and then cropped or skipped by X."""
    key = hashlib.sha1(data).hexdigest()
    hit = _card_cache.get(key)
    if hit:
        return hit
    from PIL import Image, ImageFilter, ImageOps
    img = Image.open(io.BytesIO(data))
    img.seek(0)
    img = ImageOps.exif_transpose(img).convert('RGB')
    w, h = X_CARD
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    back = img.resize((max(1, round(sw * scale)), max(1, round(sh * scale))), Image.LANCZOS)
    left, top = (back.width - w) // 2, (back.height - h) // 2
    back = back.crop((left, top, left + w, top + h)).filter(ImageFilter.GaussianBlur(28))
    back = Image.blend(back, Image.new('RGB', (w, h), (8, 9, 12)), 0.55)
    fit = min(w / sw, h / sh)
    front = img.resize((max(1, round(sw * fit)), max(1, round(sh * fit))), Image.LANCZOS)
    back.paste(front, ((w - front.width) // 2, (h - front.height) // 2))
    buf = io.BytesIO()
    back.save(buf, 'JPEG', quality=88, optimize=True, progressive=True)
    out = buf.getvalue()
    if len(_card_cache) >= 64:
        _card_cache.pop(next(iter(_card_cache)))
    _card_cache[key] = out
    return out


def _social_block(base, post_id, tc, version='', has_feed_image=False):
    safe_id = html.escape(post_id, quote=True)
    version = _safe_version(version)
    suffix = ('?xv=' + version) if version else ''
    canonical = f'{base}/post/{safe_id}{suffix}'
    image_version = html.escape(version or '10', quote=True)

    if tc:
        image = f'{base}/api/trade-card/{safe_id}.png?v={image_version}'
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
    elif has_feed_image:
        image = f'{base}/api/post-og-image/{safe_id}.jpg?v={image_version}'
        title = 'OrcAgent post'
        desc = 'View this post on OrcAgent'
    else:
        return ''

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
<meta property="og:image:type" content="{'image/jpeg' if has_feed_image and not tc else 'image/png'}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
'''


def install(dashboard_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = dashboard_module.app

    if 'orca_post_og_image' not in app.view_functions:
        @app.route('/api/post-og-image/<post_id>', endpoint='orca_post_og_image')
        def _post_og_image(post_id):
            post_id = (post_id or '')[:-4] if (post_id or '').endswith('.jpg') else post_id
            if not _POST_ID_RE.fullmatch(post_id or ''):
                return dashboard_module.make_response('Not found', 404)
            found = _feed_image(dashboard_module, post_id)
            if not found:
                return dashboard_module.make_response('Not found', 404)
            try:
                data = _x_card(found[1])
            except Exception:
                return dashboard_module.make_response('Not found', 404)
            response = dashboard_module.make_response(data)
            response.headers['Content-Type'] = 'image/jpeg'
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
            return response

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
            feed_image = None if tc else _feed_image(dashboard_module, post_id)
            if not tc and not feed_image:
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
                has_feed_image=bool(feed_image),
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
