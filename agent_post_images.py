"""Designed images for @orcagent's live feed posts.

Every live post about a call or a trending token carries a picture drawn
from the app's own live data, in one of several designs so the feed does
not look the same post after post:

  calls     - "phone":  a phone mockup with the caller's live call card in it
            - "ticket": the multiplier large, with called -> peak -> now
  trending  - "banner": the token's own Live Market banner, with the numbers
            - "chart":  a price poster with the live price line
            - "stats":  the token logo with market cap, liquidity, volume

Images are 4:5 (1080x1350) or square (1080x1080) WebP files under
DATA_DIR/agent_media, served at /media/agent/<hash>.webp. Logos and banners
come through the app's SSRF check (share_token_card._fetch_image).
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import threading
import time

from flask import abort, send_file
from PIL import Image, ImageDraw, ImageFilter

import share_token_card as stc

S = stc.S  # 2: drawn at twice the size, then downsampled
BG = (9, 10, 13)
PANEL, BORDER = (17, 19, 24), (36, 40, 48)
TEXT, SUB, MUTED = (238, 241, 245), (196, 201, 209), (138, 145, 156)
GOLD, GREEN, RED = (247, 185, 85), (58, 210, 155), (247, 107, 98)
CALL_DESIGNS = ('phone', 'ticket')
TRENDING_DESIGNS = ('banner', 'chart', 'stats')
KEEP_DAYS = 30
_NAME_RE = re.compile(r'^[0-9a-f]{40}\.webp$')
_lock = threading.Lock()


# ── drawing helpers (coordinates in output pixels, drawn at S x) ─────────

def _s(*v):
    return tuple(int(round(x * S)) for x in v)


def sans(w, size):
    return stc.sans(w, size)          # share_token_card draws at the same 2x


def mono(w, size):
    return stc.mono(w, size)


def _t(draw, xy, text, font, fill, anchor='la'):
    draw.text(_s(*xy), text, font=font, fill=fill, anchor=anchor)


def _fit(draw, text, fn, weight, size, max_w, minimum=14):
    while size > minimum and draw.textlength(text, font=fn(weight, size)) > max_w * S:
        size -= 2
    return fn(weight, size)


def _round(draw, box, r, fill=None, outline=None, width=2):
    draw.rounded_rectangle(_s(*box), radius=r * S, fill=fill, outline=outline, width=width * S if outline else 0)


def _canvas(w, h, glow=GOLD, glow_at=(0.85, 0.08)):
    img = Image.new('RGB', _s(w, h), BG)
    layer = Image.new('RGB', img.size, BG)
    gx, gy = glow_at
    r = 0.55 * w
    ImageDraw.Draw(layer).ellipse(_s(gx * w - r, gy * h - r, gx * w + r, gy * h + r),
                                  fill=tuple(int(BG[i] + (glow[i] - BG[i]) * 0.22) for i in range(3)))
    layer = layer.filter(ImageFilter.GaussianBlur(160 * S))
    return Image.blend(img, layer, 1.0)


def _brand(draw, w, y=64):
    _round(draw, (64, y, 120, y + 56), 15, fill=GOLD)
    draw.polygon([_s(92, y + 15), _s(108, y + 42), _s(76, y + 42)], fill=BG)
    _t(draw, (138, y + 28), 'OrcAgent', sans('Bold', 32), TEXT, 'lm')
    _t(draw, (w - 64, y + 28), 'orcagent.fun', mono('Medium', 24), MUTED, 'rm')


def _circle_image(img, src, box, ring=None):
    x0, y0, x1, y1 = box
    size = _s(x1 - x0, y1 - y0)
    if src is not None:
        pic = stc._cover(src, *size)
        mask = Image.new('L', size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size[0] - 1, size[1] - 1), fill=255)
        img.paste(pic, _s(x0, y0), mask)
    if ring:
        ImageDraw.Draw(img).ellipse(_s(*box), outline=ring, width=4 * S)


def _initials_circle(draw, box, text, fill=(42, 33, 22), color=GOLD, size=None):
    draw.ellipse(_s(*box), fill=fill)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    _t(draw, (cx, cy), text[:2].upper(), sans('Bold', size or int((box[2] - box[0]) * 0.34)), color, 'mm')


def _spark(img, box, points, color, fill_alpha=0.22, width=4, dot=True):
    pts = [p for p in points if p and p > 0]
    if len(pts) < 2:
        return
    x0, y0, x1, y1 = box
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or hi or 1
    xy = [(x0 + (x1 - x0) * i / (len(pts) - 1), y1 - (y1 - y0) * (p - lo) / span) for i, p in enumerate(pts)]
    area = Image.new('L', img.size, 0)
    ImageDraw.Draw(area).polygon([_s(x, y) for x, y in xy] + [_s(x1, y1), _s(x0, y1)], fill=int(255 * fill_alpha))
    area = area.filter(ImageFilter.GaussianBlur(2 * S))
    img.paste(Image.new('RGB', img.size, color), (0, 0), area)
    draw = ImageDraw.Draw(img)
    draw.line([_s(x, y) for x, y in xy], fill=color, width=width * S, joint='curve')
    if dot:
        x, y = xy[-1]
        draw.ellipse(_s(x - 9, y - 9, x + 9, y + 9), fill=color)


def _wrap(draw, text, font, max_w, lines=2):
    words, out, cur = (text or '').split(), [], ''
    for w in words:
        nxt = (cur + ' ' + w).strip()
        if draw.textlength(nxt, font=font) <= max_w * S:
            cur = nxt
        else:
            out.append(cur)
            cur = w
            if len(out) == lines:
                break
    if len(out) < lines and cur:
        out.append(cur)
    if len(out) == lines and ' '.join(out) != ' '.join(words):
        out[-1] = out[-1].rstrip('.,;:') + '…'
    return out


def _accent(logo):
    if logo is None:
        return GOLD
    c = logo.resize((1, 1), Image.LANCZOS).getpixel((0, 0))
    if sum(c) < 120:
        return GOLD
    return c


def _pct(v):
    return '%+.1f%%' % float(v or 0)


def _mult(x):
    return ('%.2f' % x).rstrip('0').rstrip('.') + 'x'


def _finish(img, w, h):
    out = img.resize((w, h), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, 'WEBP', quality=86, method=5)
    return buf.getvalue()


# ── call designs ───────────────────────────────────────────────────────

def _call_card(img, draw, x0, y0, w, c, logo, points):
    """The in-app call card: token, multiplier, price line, three tiles, buttons."""
    x1 = x0 + w
    _round(draw, (x0, y0, x1, y0 + 560), 28, fill=PANEL, outline=BORDER)
    if logo is not None:
        _circle_image(img, logo, (x0 + 28, y0 + 28, x0 + 112, y0 + 112))
    else:
        _initials_circle(draw, (x0 + 28, y0 + 28, x0 + 112, y0 + 112), c['symbol'])
    _t(draw, (x0 + 132, y0 + 52), '$' + c['symbol'], _fit(draw, '$' + c['symbol'], sans, 'Bold', 40, w - 360), TEXT, 'lm')
    _t(draw, (x0 + 132, y0 + 92), (c.get('name') or c['symbol'])[:22] + ' · Solana', sans('Medium', 24), MUTED, 'lm')
    color = GREEN if c['multiplier'] >= 1 else RED
    _t(draw, (x1 - 28, y0 + 58), _mult(c['multiplier']), mono('ExtraBold', 60), color, 'rm')
    _t(draw, (x1 - 28, y0 + 100), 'peak since call', sans('Medium', 20), MUTED, 'rm')
    _spark(img, (x0 + 28, y0 + 140, x1 - 28, y0 + 300), points, color)
    draw = ImageDraw.Draw(img)
    tw = (w - 56 - 32) / 3
    for i, (label, value, col) in enumerate((('Called at', c['called'], TEXT), ('Now', c['now'], color), ('Peak', c['peak'], GREEN))):
        tx = x0 + 28 + i * (tw + 16)
        _round(draw, (tx, y0 + 330, tx + tw, y0 + 430), 16, fill=(23, 26, 32))
        _t(draw, (tx + 18, y0 + 360), label, sans('Medium', 21), MUTED, 'lm')
        _t(draw, (tx + 18, y0 + 400), value, _fit(draw, value, mono, 'Bold', 30, tw - 30), col, 'lm')
    bw = (w - 56 - 24) / 3
    for i, (label, filled) in enumerate((('Buy $' + c['symbol'], True), ('Share call', False), ('Chart', False))):
        bx = x0 + 28 + i * (bw + 12)
        _round(draw, (bx, y0 + 458, bx + bw, y0 + 530), 18, fill=GOLD if filled else None,
               outline=None if filled else (58, 62, 72))
        _t(draw, (bx + bw / 2, y0 + 494), label, _fit(draw, label, sans, 'Bold', 26, bw - 24),
           BG if filled else (GOLD if i == 1 else TEXT), 'mm')
    return draw


def call_phone(c, logo, points):
    w, h = 1080, 1350
    img = _canvas(w, h, GOLD, (0.9, 0.05))
    draw = ImageDraw.Draw(img)
    _brand(draw, w)
    head = c['headline']
    _t(draw, (64, 236), head, _fit(draw, head, sans, 'ExtraBold', 92, w - 128), TEXT, 'ls')
    _t(draw, (64, 298), 'by @' + c['user'], sans('Bold', 44), GOLD, 'ls')
    # phone
    px0, py0, px1 = 150, 360, 930
    _round(draw, (px0, py0, px1, h + 80), 70, fill=(20, 22, 27), outline=(52, 56, 64), width=3)
    _round(draw, (px0 + 18, py0 + 18, px1 - 18, h + 80), 54, fill=(10, 11, 14))
    _round(draw, ((px0 + px1) / 2 - 70, py0 + 34, (px0 + px1) / 2 + 70, py0 + 62), 14, fill=(20, 22, 27))
    sx = px0 + 52
    sw = px1 - px0 - 104
    _initials_circle(draw, (sx, py0 + 100, sx + 76, py0 + 176), c['user'], fill=(26, 22, 16))
    _t(draw, (sx + 96, py0 + 124), '@' + c['user'], sans('Bold', 30), TEXT, 'lm')
    _round(draw, (sx + 96, py0 + 146, sx + 222, py0 + 182), 9, outline=(120, 92, 40), width=2)
    _t(draw, (sx + 159, py0 + 164), 'CALLED', sans('Bold', 20), GOLD, 'mm')
    _t(draw, (sx + 238, py0 + 164), '· ' + c['ago'], sans('Medium', 22), MUTED, 'lm')
    y = py0 + 220
    for line in _wrap(draw, c.get('note') or ('Calling $%s here.' % c['symbol']), sans('Medium', 30), sw, 2):
        _t(draw, (sx, y), line, sans('Medium', 30), SUB, 'lm')
        y += 44
    _call_card(img, draw, sx, y + 12, sw, c, logo, points)
    return _finish(img, w, h)


def call_ticket(c, logo, points):
    w, h = 1080, 1080
    img = _canvas(w, h, GREEN if c['multiplier'] >= 1.2 else GOLD, (0.1, 0.9))
    draw = ImageDraw.Draw(img)
    _brand(draw, w)
    _round(draw, (64, 170, 64 + 26 + draw.textlength(c['label'], font=sans('Bold', 24)) / S + 26, 216), 12, fill=GOLD)
    _t(draw, (90, 193), c['label'], sans('Bold', 24), BG, 'lm')
    if logo is not None:
        _circle_image(img, logo, (64, 250, 164, 350))
    else:
        _initials_circle(draw, (64, 250, 164, 350), c['symbol'])
    _t(draw, (190, 292), '$' + c['symbol'], _fit(draw, '$' + c['symbol'], sans, 'ExtraBold', 64, 560), TEXT, 'lm')
    _t(draw, (190, 338), 'called by @' + c['user'] + ' · ' + c['ago'], sans('Medium', 28), MUTED, 'lm')
    big = _mult(c['multiplier']) if c['multiplier'] >= 1.2 else c['called']
    color = GREEN if c['multiplier'] >= 1.2 else TEXT
    _t(draw, (64, 600), big, _fit(draw, big, mono, 'ExtraBold', 230, w - 128), color, 'ls')
    _t(draw, (68, 650), 'peak since the call' if c['multiplier'] >= 1.2 else 'market cap at the call', sans('Medium', 30), MUTED, 'ls')
    # called -> peak -> now
    ys, xs = 790, (110, 540, 970)
    draw.line([_s(xs[0], ys), _s(xs[2], ys)], fill=(52, 56, 64), width=4 * S)
    for x, (label, value, col) in zip(xs, (('CALLED', c['called'], TEXT), ('PEAK', c['peak'], GREEN), ('NOW', c['now'], GREEN if c['now_x'] >= 1 else RED))):
        draw.ellipse(_s(x - 14, ys - 14, x + 14, ys + 14), fill=col if label != 'CALLED' else GOLD)
        _t(draw, (x, ys - 46), label, sans('Bold', 22), MUTED, 'mm')
        _t(draw, (x, ys + 56), value, mono('Bold', 36), col, 'mm')
    note = c.get('note')
    if note:
        lines = _wrap(draw, '“' + note + '”', sans('Medium', 30), w - 128, 2)
        for i, line in enumerate(lines):
            _t(draw, (64, 920 + i * 44), line, sans('Medium', 30), SUB, 'lm')
    else:
        _t(draw, (64, 940), 'Every call keeps its entry. Open it on OrcAgent.', sans('Medium', 30), SUB, 'lm')
    return _finish(img, w, h)


# ── trending designs ───────────────────────────────────────────────────

def _flame(draw, cx, cy, size, fill):
    r = size / 2
    pts = [(cx, cy - r), (cx + r * .55, cy - r * .1), (cx + r * .62, cy + r * .38), (cx + r * .3, cy + r * .78),
           (cx, cy + r * .88), (cx - r * .3, cy + r * .78), (cx - r * .62, cy + r * .38), (cx - r * .5, cy),
           (cx - r * .12, cy - r * .3)]
    draw.polygon([_s(x, y) for x, y in pts], fill=fill)


def _trend_pill(draw, x, y, text='TRENDING ON LIVE MARKET'):
    tw = draw.textlength(text, font=sans('Bold', 24)) / S
    _round(draw, (x, y, x + tw + 76, y + 50), 14, fill=GOLD)
    _flame(draw, x + 30, y + 25, 26, BG)
    _t(draw, (x + 52, y + 26), text, sans('Bold', 24), BG, 'lm')


def _stat(draw, box, label, value, col=TEXT):
    x0, y0, x1, y1 = box
    _round(draw, box, 20, fill=PANEL, outline=BORDER)
    _t(draw, (x0 + 26, y0 + 40), label, sans('Medium', 24), MUTED, 'lm')
    _t(draw, (x0 + 26, y1 - 40), value, _fit(draw, value, mono, 'Bold', 40, x1 - x0 - 52), col, 'lm')


def _buy_bar(draw, x0, y, x1, t):
    buys, sells = int(t.get('buys_24h') or 0), int(t.get('sells_24h') or 0)
    if buys + sells <= 0:
        return
    share = buys / (buys + sells)
    _t(draw, (x0, y), 'Buys %d%%' % round(share * 100), sans('Bold', 26), GREEN, 'lm')
    _t(draw, (x1, y), 'Sells %d%%' % round((1 - share) * 100), sans('Bold', 26), RED, 'rm')
    _round(draw, (x0, y + 26, x1, y + 42), 8, fill=(60, 30, 32))
    _round(draw, (x0, y + 26, x0 + (x1 - x0) * share, y + 42), 8, fill=GREEN)


def trend_banner(t, logo, banner, points):
    w, h = 1080, 1350
    img = _canvas(w, h, _accent(logo), (0.5, 0.0))
    accent = _accent(logo)
    bh = 640
    if banner is not None:
        top = stc._cover(banner, *_s(w, bh))
    else:
        top = stc._vgradient(*_s(w, bh), tuple(int(c * 0.55) for c in accent), BG)
        d2 = ImageDraw.Draw(top)
        for i in range(-12, 24):
            d2.line([_s(i * 90, 0), _s(i * 90 + 640, bh)], fill=tuple(min(255, int(c * 0.6) + 8) for c in accent), width=10 * S)
        top = top.filter(ImageFilter.GaussianBlur(6 * S))
    # Fade the banner out over the canvas itself, so there is no seam.
    keep = Image.new('L', top.size, 0)
    fd = ImageDraw.Draw(keep)
    for i in range(top.size[1]):
        fd.line([(0, i), (top.size[0], i)], fill=int(255 * (1 - min(1, max(0, (i / top.size[1] - 0.4) / 0.6)))))
    img.paste(top, (0, 0), keep)
    draw = ImageDraw.Draw(img)
    _trend_pill(draw, 64, 64)
    if logo is not None:
        _circle_image(img, logo, (64, 470, 244, 650), ring=BG)
    else:
        _initials_circle(draw, (64, 470, 244, 650), t['symbol'])
    draw = ImageDraw.Draw(img)
    _t(draw, (64, 760), '$' + t['symbol'], _fit(draw, '$' + t['symbol'], sans, 'ExtraBold', 104, w - 128), TEXT, 'ls')
    _t(draw, (68, 808), (t.get('name') or t['symbol'])[:30] + ' · Solana', sans('Medium', 32), MUTED, 'ls')
    price = stc.fmt_price(t.get('price_usd'))
    _t(draw, (64, 900), price, _fit(draw, price, mono, 'ExtraBold', 76, 620), TEXT, 'ls')
    chg = float(t.get('price_change_24h') or 0)
    pill = _pct(chg) + ' 24h'
    pw = draw.textlength(pill, font=sans('Bold', 32)) / S + 44
    _round(draw, (w - 64 - pw, 846, w - 64, 906), 16, fill=(20, 52, 40) if chg >= 0 else (60, 26, 26))
    _t(draw, (w - 64 - pw / 2, 876), pill, sans('Bold', 32), GREEN if chg >= 0 else RED, 'mm')
    _spark(img, (64, 950, w - 64, 1120), points, GREEN if chg >= 0 else RED)
    draw = ImageDraw.Draw(img)
    cw = (w - 128 - 32) / 3
    for i, (label, val) in enumerate((('Market cap', stc.fmt_compact(t.get('market_cap'))),
                                      ('Liquidity', stc.fmt_compact(t.get('liquidity_usd'))),
                                      ('Volume 24h', stc.fmt_compact(t.get('volume_24h'))))):
        x = 64 + i * (cw + 16)
        _stat(draw, (x, 1160, x + cw, 1290), label, val)
    return _finish(img, w, h)


def trend_chart(t, logo, banner, points):
    w, h = 1080, 1080
    chg = float(t.get('price_change_24h') or 0)
    color = GREEN if chg >= 0 else RED
    img = _canvas(w, h, color, (0.5, 1.0))
    draw = ImageDraw.Draw(img)
    _brand(draw, w)
    if logo is not None:
        _circle_image(img, logo, (64, 170, 164, 270))
    else:
        _initials_circle(draw, (64, 170, 164, 270), t['symbol'])
    draw = ImageDraw.Draw(img)
    _t(draw, (190, 206), '$' + t['symbol'], _fit(draw, '$' + t['symbol'], sans, 'ExtraBold', 60, 560), TEXT, 'lm')
    _flame(draw, 204, 250, 24, GOLD)
    _t(draw, (224, 251), 'Trending on Live Market', sans('Bold', 26), GOLD, 'lm')
    price = stc.fmt_price(t.get('price_usd'))
    _t(draw, (64, 430), price, _fit(draw, price, mono, 'ExtraBold', 140, w - 128), TEXT, 'ls')
    _t(draw, (68, 500), _pct(chg) + ' in 24 hours', sans('Bold', 48), color, 'ls')
    _spark(img, (0, 560, w, 940), points, color, fill_alpha=0.32, width=7)
    draw = ImageDraw.Draw(img)
    _buy_bar(draw, 64, 990, w - 64, t)
    return _finish(img, w, h)


def trend_stats(t, logo, banner, points):
    w, h = 1080, 1350
    accent = _accent(logo)
    img = _canvas(w, h, accent, (0.5, 0.28))
    draw = ImageDraw.Draw(img)
    _brand(draw, w)
    cx = w / 2
    glow = Image.new('L', img.size, 0)
    ImageDraw.Draw(glow).ellipse(_s(cx - 200, 220, cx + 200, 620), fill=110)
    glow = glow.filter(ImageFilter.GaussianBlur(50 * S))
    img.paste(Image.new('RGB', img.size, accent), (0, 0), glow)
    if logo is not None:
        _circle_image(img, logo, (cx - 140, 280, cx + 140, 560), ring=GOLD)
    else:
        _initials_circle(ImageDraw.Draw(img), (cx - 140, 280, cx + 140, 560), t['symbol'])
    draw = ImageDraw.Draw(img)
    _t(draw, (cx, 680), '$' + t['symbol'], _fit(draw, '$' + t['symbol'], sans, 'ExtraBold', 110, w - 128), TEXT, 'ms')
    chg = float(t.get('price_change_24h') or 0)
    label = 'TRENDING · ' + _pct(chg) + ' TODAY'
    lw = draw.textlength(label, font=sans('Bold', 30)) / S + 90
    _round(draw, (cx - lw / 2, 712, cx + lw / 2, 772), 18, fill=GOLD)
    _flame(draw, cx - lw / 2 + 36, 742, 28, BG)
    _t(draw, (cx + 18, 742), label, sans('Bold', 30), BG, 'mm')
    cw = (w - 128 - 24) / 2
    tiles = (('Price', stc.fmt_price(t.get('price_usd'))), ('Market cap', stc.fmt_compact(t.get('market_cap'))),
             ('Liquidity', stc.fmt_compact(t.get('liquidity_usd'))), ('Volume 24h', stc.fmt_compact(t.get('volume_24h'))))
    for i, (lab, val) in enumerate(tiles):
        x = 64 + (i % 2) * (cw + 24)
        y = 830 + (i // 2) * 170
        _stat(draw, (x, y, x + cw, y + 146), lab, val)
    _buy_bar(draw, 64, 1220, w - 64, t)
    return _finish(img, w, h)


RENDER = {'phone': call_phone, 'ticket': call_ticket,
          'banner': trend_banner, 'chart': trend_chart, 'stats': trend_stats}


# ── storage and the public route ───────────────────────────────────────

def media_dir(d):
    base = os.path.dirname(str(d.DB_FILE)) or '.'
    path = os.path.join(base, 'agent_media')
    os.makedirs(path, exist_ok=True)
    return path


def save(d, data: bytes) -> str:
    name = hashlib.sha1(data).hexdigest() + '.webp'
    path = os.path.join(media_dir(d), name)
    if not os.path.exists(path):
        tmp = path + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, path)
    return '/media/agent/' + name


def prune(d, now=None):
    """Drop images older than KEEP_DAYS, and the picture from their posts."""
    now = now or time.time()
    folder = media_dir(d)
    gone = []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if _NAME_RE.match(name) and now - os.path.getmtime(p) > KEEP_DAYS * 86400:
            os.remove(p)
            gone.append('/media/agent/' + name)
    if gone:
        import sqlite3
        with sqlite3.connect(d.DB_FILE, timeout=10) as c:
            c.executemany('UPDATE feed_posts SET image_url=NULL WHERE image_url=?', [(g,) for g in gone])
    return len(gone)


def _call_view(d, m):
    p0 = float(m['price_at_call'])
    peak = max(float(m.get('peak_price') or 0), p0)
    now_p = float(m.get('last_price') or 0) or p0
    mc0 = float(m.get('mcap_at_call') or 0)
    x = peak / p0
    try:
        ts = time.mktime(time.strptime(m['timestamp'][:19], '%Y-%m-%d %H:%M:%S')) - time.timezone
        mins = max(1, int((time.time() - ts) / 60))
        ago = '%dm' % mins if mins < 60 else ('%dh' % (mins // 60) if mins < 1440 else '%dd' % (mins // 1440))
    except Exception:
        ago = 'now'
    head = {'milestone': '%dX CALL' % int(m.get('milestone') or x), 'best': 'CALL OF THE DAY'}.get(m.get('event'), 'NEW CALL')
    label = {'milestone': '%dX SINCE THE CALL' % int(m.get('milestone') or x), 'best': 'BEST CALL TODAY'}.get(m.get('event'), 'NEW CALL')
    return {'symbol': m.get('symbol') or '?', 'name': m.get('token_name') or '', 'user': m['user'],
            'note': re.sub(r'\s+', ' ', str(m.get('note') or '')).strip()[:160],
            'multiplier': x, 'now_x': now_p / p0, 'called': stc.fmt_compact(mc0) if mc0 else stc.fmt_price(p0),
            'peak': stc.fmt_compact(mc0 * x) if mc0 else stc.fmt_price(peak),
            'now': stc.fmt_compact(mc0 * now_p / p0) if mc0 else stc.fmt_price(now_p),
            'ago': ago, 'headline': head, 'label': label}


def make(d, media, seed, variant=None):
    """Render the picture for one live post; returns its URL or None.

    variant, when given, picks the design in turn (the caller passes how many
    pictures of this kind went out before), so two posts in a row never share
    a design; otherwise the seed picks one."""
    if not media:
        return None
    try:
        kind, data = media['kind'], dict(media['data'])
        designs = CALL_DESIGNS if kind == 'call' else TRENDING_DESIGNS
        n = int(variant) if variant is not None else int(hashlib.sha256(str(seed).encode()).hexdigest()[:8], 16)
        design = designs[n % len(designs)]
        import trending_share as ts
        if kind == 'call':
            view = _call_view(d, data)
            logo = stc._fetch_image(d, data.get('image_url'))
            pts = ts.price_points(d, {'mint': data['mint'], 'chain': 'solana', 'pair_address': '',
                                      'price_usd': float(data.get('last_price') or data['price_at_call'])})
            if len(pts) < 3:
                p0 = float(data['price_at_call'])
                pts = [p0, (p0 + float(data.get('peak_price') or p0)) / 2, float(data.get('peak_price') or p0),
                       float(data.get('last_price') or p0)]
            data_bytes = RENDER[design](view, logo, pts)
        else:
            data.setdefault('chain', 'solana')
            logo = stc._fetch_image(d, data.get('image_url'))
            banner = stc._fetch_image(d, data.get('banner_url'))
            # No banner on DexScreener: the banner design draws its own
            # backdrop in the token's colour, so the turn order still holds.
            pts = ts.price_points(d, data)
            data_bytes = RENDER[design](data, logo, banner, pts)
        return save(d, data_bytes)
    except Exception as exc:
        print('[agent-image] %s render failed: %s' % ((media or {}).get('kind'), exc), flush=True)
        return None


def install(d):
    app = d.app
    if getattr(app, '_orca_agent_images_installed', False):
        return
    app._orca_agent_images_installed = True

    @app.route('/media/agent/<name>')
    def agent_post_image(name):
        if not _NAME_RE.match(name or ''):
            abort(404)
        path = os.path.join(media_dir(d), name)
        if not os.path.isfile(path):
            abort(404)
        resp = send_file(path, mimetype='image/webp', max_age=31536000)
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return resp
