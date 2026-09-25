"""The X/Open Graph preview of a token (chart) post is the token card itself.

A post that embeds a token (__CHART__) shows a rich card in the app: banner,
logo, chain pill, symbol, name, DEX tag, price, 24h change, sparkline,
24h volume / liquidity / market cap / FDV, buys vs sells, 5m/1h/6h/24h
changes, the pair and "View Token". Shared to X it used to unfurl as a
different, much simpler picture. This renders that same card -- same
blocks, colours and typefaces (Geist + JetBrains Mono, bundled under
fonts/, SIL OFL 1.1) -- as the 1200x630 PNG X shows.

X shows link previews at 1.91:1 and crops anything taller, so the card's
blocks are laid out in two columns instead of one tall stack: nothing is
cut off, and every field from the app card is on it.

Numbers come from the post itself, refreshed with the pair's live
DexScreener data when that is reachable (the app card is live too). The
sparkline is drawn through the pair's real price at -24h, -6h, -1h, -5m and
now, derived from DexScreener's own change figures -- never invented.
Remote images (banner, logo) pass the app's SSRF check, are fetched without
following redirects and are size-capped. Rendered PNGs are cached briefly.
"""
from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import threading
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, S = 1200, 630, 2          # output size; drawn at S x and downsampled
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
CACHE_SECONDS = 300
MAX_IMAGE_BYTES = 4 * 1024 * 1024

BG = (7, 11, 16)
CARD_TOP, CARD_BOTTOM = (11, 17, 24), (10, 15, 21)
BORDER = (32, 42, 54)
PANEL, PANEL_BORDER = (17, 24, 33), (28, 38, 49)
PAIR_BG = (15, 21, 29)
TEXT, MUTED, LABEL = (244, 247, 251), (143, 153, 168), (112, 123, 139)
GREEN, RED, GOLD = (54, 215, 160), (255, 113, 106), (247, 185, 85)
CHAINS = {'solana': 'SOL', 'bsc': 'BNB', 'base': 'BASE', 'arbitrum': 'ARB',
          'polygon': 'POLYGON', 'robinhood': 'ROBINHOOD'}

_cache: dict = {}
_cache_lock = threading.Lock()
_fonts: dict = {}


def _font(family, weight, size):
    key = (family, weight, size)
    if key not in _fonts:
        path = os.path.join(FONT_DIR, f'{family}-{weight}.ttf')
        try:
            _fonts[key] = ImageFont.truetype(path, size * S)
        except Exception:
            _fonts[key] = ImageFont.load_default()
    return _fonts[key]


def sans(weight, size):
    return _font('Geist', weight, size)


def mono(weight, size):
    return _font('JetBrainsMono', weight, size)


def _num(v):
    try:
        n = float(v)
        return n if n == n and abs(n) != float('inf') else None
    except (TypeError, ValueError):
        return None


def fmt_money(v):
    n = _num(v)
    if n is None:
        return '—'
    if abs(n) >= 1e9:
        return f'${n / 1e9:.2f}B'
    if abs(n) >= 1e6:
        return f'${n / 1e6:.2f}M'
    if abs(n) >= 1e3:
        return '$' + f'{round(n):,}'
    return f'${n:.2f}'


def fmt_compact(v):
    """$826.8K / $1.25M -- how the app card shows 24h volume and liquidity."""
    n = _num(v)
    if n is None:
        return '—'
    if n >= 1e9:
        return f'${n / 1e9:.2f}B'
    if n >= 1e6:
        return f'${n / 1e6:.2f}M'
    if n >= 1e3:
        return f'${n / 1e3:.1f}K'
    return f'${n:.2f}'


def fmt_price(v):
    n = _num(v)
    if not n:
        return '—'
    if n >= 1:
        return f'${n:.2f}'
    if n >= .01:
        return f'${n:.4f}'
    if n >= .001:
        return f'${n:.6f}'
    return '$' + f'{n:.8f}'.rstrip('0').rstrip('.')


def fmt_pct(v):
    n = _num(v)
    return '—' if n is None else f'{"+" if n >= 0 else ""}{n:.2f}%'


def short_pair(s):
    s = str(s or '')
    return s[:7] + '…' + s[-5:] if len(s) > 14 else (s or '—')


# ── data ────────────────────────────────────────────────────────────────
def post_chart_data(d, post_id):
    """The __CHART__ JSON of feed post p<id>, or None."""
    if not re.fullmatch(r'p\d+', post_id or ''):
        return None
    conn = sqlite3.connect(d.DB_FILE)
    try:
        row = conn.execute('SELECT content FROM feed_posts WHERE id=?', (post_id[1:],)).fetchone()
    finally:
        conn.close()
    content = (row[0] if row else '') or ''
    i = content.find('__CHART__')
    if i < 0:
        return None
    try:
        data = json.loads(content[i + len('__CHART__'):])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _live_pair(d, c):
    """The pair's live DexScreener row, or None."""
    try:
        pair, chain, mint = (c.get('pairAddress') or ''), (c.get('chain') or ''), (c.get('mint') or '')
        r = None
        if pair and chain:
            r = d._dex_get(f'https://api.dexscreener.com/latest/dex/pairs/{chain}/{pair}', timeout=6)
            rows = (r.json().get('pairs') or []) if (r and r.status_code == 200) else []
            if rows:
                return rows[0]
        if mint:
            r = d._dex_get('https://api.dexscreener.com/latest/dex/tokens/' + mint, timeout=6)
            rows = (r.json().get('pairs') or []) if (r and r.status_code == 200) else []
            rows = [p for p in rows if not chain or p.get('chainId') == chain] or rows
            if rows:
                return max(rows, key=lambda p: _num((p.get('liquidity') or {}).get('usd')) or 0)
    except Exception:
        return None
    return None


def card_data(d, c, live=True):
    """Everything the card shows: the post's own values, refreshed live."""
    out = {
        'symbol': str(c.get('symbol') or '?'), 'name': str(c.get('name') or ''),
        'chain': str(c.get('chain') or '').lower(), 'dex': str(c.get('dexId') or c.get('dex') or ''),
        'banner': c.get('banner') or '', 'image': c.get('image') or '',
        'pair': c.get('pairAddress') or '', 'price': _num(c.get('price')),
        'chg5m': _num(c.get('chg5m')), 'chg1h': _num(c.get('chg1h')),
        'chg6h': _num(c.get('chg6h')), 'chg24h': _num(c.get('chg24h')),
        'vol': _num(c.get('vol24h')), 'liq': _num(c.get('liq')),
        'mcap': _num(c.get('marketCap')), 'fdv': _num(c.get('fdv')),
        'buys': int(_num(c.get('buys')) or 0), 'sells': int(_num(c.get('sells')) or 0),
    }
    p = _live_pair(d, c) if live else None
    if p:
        pc, tx = p.get('priceChange') or {}, ((p.get('txns') or {}).get('h24') or {})
        info, base = p.get('info') or {}, p.get('baseToken') or {}
        fresh = {
            'price': _num(p.get('priceUsd')), 'chg5m': _num(pc.get('m5')), 'chg1h': _num(pc.get('h1')),
            'chg6h': _num(pc.get('h6')), 'chg24h': _num(pc.get('h24')),
            'vol': _num((p.get('volume') or {}).get('h24')), 'liq': _num((p.get('liquidity') or {}).get('usd')),
            'mcap': _num(p.get('marketCap')), 'fdv': _num(p.get('fdv')),
            'buys': int(_num(tx.get('buys')) or 0) or None, 'sells': int(_num(tx.get('sells')) or 0) or None,
            'banner': info.get('header'), 'image': info.get('imageUrl'), 'dex': p.get('dexId'),
            'name': base.get('name'), 'pair': p.get('pairAddress'), 'chain': p.get('chainId'),
        }
        out.update({k: v for k, v in fresh.items() if v not in (None, '')})
    return out


def spark_points(price, chg24h, chg6h, chg1h, chg5m):
    """Real prices at -24h, -6h, -1h, -5m and now, from DexScreener's change
    figures (price_then = price_now / (1 + change%)). Missing ones are skipped."""
    if not price:
        return []
    pts = []
    for chg in (chg24h, chg6h, chg1h, chg5m):
        if chg is not None and chg > -99.9:
            pts.append(price / (1 + chg / 100))
    return pts + [price]


# ── drawing ─────────────────────────────────────────────────────────────
def _s(*v):
    return tuple(int(round(x * S)) for x in v)


def _panel(draw, box, fill=PANEL, outline=PANEL_BORDER, r=14):
    draw.rounded_rectangle(_s(*box), radius=r * S, fill=fill, outline=outline, width=S)


def _text(draw, xy, text, font, fill, anchor='la'):
    draw.text(_s(*xy), text, font=font, fill=fill, anchor=anchor)


def _fit(draw, text, font_fn, weight, size, max_w, minimum=10):
    while size > minimum and draw.textlength(text, font=font_fn(weight, size)) > max_w * S:
        size -= 1
    return font_fn(weight, size)


def _fetch_image(d, url):
    if not url or not str(url).startswith('https://'):
        return None
    try:
        if not d._safe_external_image_url(url):
            return None
        r = d.requests.get(url, timeout=5, stream=True, allow_redirects=False)
        if r.status_code != 200:
            return None
        data = r.raw.read(MAX_IMAGE_BYTES + 1, decode_content=True)
        if len(data) > MAX_IMAGE_BYTES:
            return None
        return Image.open(io.BytesIO(data)).convert('RGB')
    except Exception:
        return None


def _cover(img, w, h):
    sw, sh = img.size
    scale = max(w / sw, h / sh)
    img = img.resize((max(1, round(sw * scale)), max(1, round(sh * scale))), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _vgradient(w, h, top, bottom):
    g = Image.new('RGB', (1, 2))
    g.putpixel((0, 0), top); g.putpixel((0, 1), bottom)
    return g.resize((w, h), Image.BILINEAR)


def render(card, banner_img=None, logo_img=None) -> bytes:
    """Draw the card. Pure: all data and images are passed in."""
    img = Image.new('RGB', _s(W, H), BG)
    x0, y0, x1, y1 = 24, 24, W - 24, H - 24
    cw, ch = x1 - x0, y1 - y0
    # Card body with a subtle vertical gradient and the app card's border.
    body = _vgradient(cw * S, ch * S, CARD_TOP, CARD_BOTTOM)
    mask = Image.new('L', body.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, body.width - 1, body.height - 1), radius=26 * S, fill=255)
    img.paste(body, _s(x0, y0), mask)

    # Hero banner across the top, shaded towards the card like the app.
    hero_h = 168
    hero = _cover(banner_img, cw * S, hero_h * S) if banner_img else Image.new('RGB', (cw * S, hero_h * S), (13, 19, 26))
    shade = Image.new('RGBA', hero.size)
    sd = ImageDraw.Draw(shade)
    for yy in range(hero.height):
        t = yy / max(1, hero.height - 1)
        a = int(255 * (0.05 + (0.18 - 0.05) * min(1, t / .58))) if t < .58 else int(255 * (0.18 + (0.9 - 0.18) * (t - .58) / .42))
        sd.line([(0, yy), (hero.width, yy)], fill=(7, 11, 16, a))
    hero = Image.alpha_composite(hero.convert('RGBA'), shade).convert('RGB')
    hmask = Image.new('L', hero.size, 0)
    ImageDraw.Draw(hmask).rounded_rectangle((0, 0, hero.width - 1, hero.height + 60 * S), radius=26 * S, fill=255)
    img.paste(hero, _s(x0, y0), hmask)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(_s(x0, y0, x1, y1), radius=26 * S, outline=BORDER, width=2 * S)

    # Chain pill, top right of the banner.
    chain = CHAINS.get(card['chain'], (card['chain'] or 'CHAIN').upper())
    f = sans('ExtraBold', 17)
    pw = draw.textlength(chain, font=f) / S + 46
    px1, py0 = x1 - 20, y0 + 20
    draw.rounded_rectangle(_s(px1 - pw, py0, px1, py0 + 38), radius=12 * S, fill=(6, 10, 15), outline=(52, 58, 66), width=S)
    draw.ellipse(_s(px1 - pw + 16, py0 + 14, px1 - pw + 27, py0 + 25), fill=(120, 110, 246))
    _text(draw, (px1 - pw + 34, py0 + 19), chain, f, TEXT, 'lm')

    # Logo overlapping the banner, gold ring, then symbol / name / DEX tag.
    lx, ly, ls = x0 + 30, y0 + hero_h - 52, 104
    draw.ellipse(_s(lx - 5, ly - 5, lx + ls + 5, ly + ls + 5), fill=GOLD)
    draw.ellipse(_s(lx, ly, lx + ls, ly + ls), fill=(23, 29, 37))
    if logo_img:
        lg = _cover(logo_img, ls * S, ls * S)
        lm = Image.new('L', lg.size, 0)
        ImageDraw.Draw(lm).ellipse((0, 0, lg.width - 1, lg.height - 1), fill=255)
        img.paste(lg, _s(lx, ly), lm)
    else:
        _text(draw, (lx + ls / 2, ly + ls / 2), card['symbol'][:2].upper(), sans('ExtraBold', 30), GOLD, 'mm')
    tx = lx + ls + 22
    sym = '$' + card['symbol']
    _text(draw, (tx, ly + 40), sym, _fit(draw, sym, mono, 'ExtraBold', 42, 470, 24), TEXT, 'ls')
    name = card['name'][:28]
    nf = sans('Medium', 20)
    _text(draw, (tx, ly + 76), name, nf, MUTED, 'ls')
    if card['dex']:
        dex = card['dex'].upper()[:14]
        dx = tx + (draw.textlength(name, font=nf) / S + 14 if name else 0)
        df = sans('ExtraBold', 15)
        dw = draw.textlength(dex, font=df) / S + 22
        draw.rounded_rectangle(_s(dx, ly + 55, dx + dw, ly + 84), radius=8 * S, fill=(49, 39, 20), outline=(95, 74, 37), width=S)
        _text(draw, (dx + dw / 2, ly + 70), dex, df, GOLD, 'mm')

    # Left column: price, 24h change, sparkline.
    lc0, top = x0 + 30, y0 + hero_h + 74
    price = fmt_price(card['price'])
    _text(draw, (lc0, top + 58), price, _fit(draw, price, mono, 'ExtraBold', 62, 470, 30), TEXT, 'ls')
    chg = card['chg24h']
    col = RED if (chg or 0) < 0 else GREEN
    cf = sans('ExtraBold', 28)
    ctext = fmt_pct(chg)
    _text(draw, (lc0, top + 104), ctext, cf, col, 'ls')
    _text(draw, (lc0 + draw.textlength(ctext, font=cf) / S + 10, top + 104), '24h', sans('Medium', 18), (120, 131, 146), 'ls')
    pts = spark_points(card['price'], card['chg24h'], card['chg6h'], card['chg1h'], card['chg5m'])
    sx0, sy0, sx1, sy1 = lc0, top + 138, lc0 + 480, y1 - 36
    if len(pts) >= 2:
        lo, hi = min(pts), max(pts)
        hi = hi if hi > lo else lo * 1.01 + 1e-12
        coords = [(sx0 + (sx1 - sx0) * i / (len(pts) - 1), sy1 - (sy1 - sy0) * (v - lo) / (hi - lo)) for i, v in enumerate(pts)]
        area = Image.new('RGBA', img.size)
        ad = ImageDraw.Draw(area)
        ad.polygon([_s(*p) for p in coords] + [_s(sx1, sy1), _s(sx0, sy1)], fill=col + (38,))
        img.paste(area, (0, 0), area)
        draw = ImageDraw.Draw(img)
        draw.line([_s(*p) for p in coords], fill=col, width=5 * S, joint='curve')
        ex, ey = coords[-1]
        draw.ellipse(_s(ex - 8, ey - 8, ex + 8, ey + 8), fill=col)

    # Right column: stats, buys/sells, change chips, pair + View Token.
    rc0, rc1 = x0 + 560, x1 - 26
    rw = rc1 - rc0
    ry = y0 + hero_h + 16
    gw, gh, gap = (rw - 12) / 2, 74, 12
    stats = [('24H VOLUME', fmt_compact(card['vol'])), ('LIQUIDITY', fmt_compact(card['liq'])),
             ('MARKET CAP', fmt_money(card['mcap'])), ('FDV', fmt_money(card['fdv']))]
    for i, (label, value) in enumerate(stats):
        bx, by = rc0 + (i % 2) * (gw + gap), ry + (i // 2) * (gh + 10)
        _panel(draw, (bx, by, bx + gw, by + gh))
        _text(draw, (bx + 18, by + 26), label, sans('Bold', 14), LABEL, 'ls')
        _text(draw, (bx + 18, by + 58), value, _fit(draw, value, mono, 'Bold', 26, gw - 34, 14), TEXT, 'ls')
    fy = ry + 2 * (gh + 10)
    _panel(draw, (rc0, fy, rc1, fy + 74))
    buys, sells = card['buys'], card['sells']
    tot = buys + sells
    bp = (buys / tot * 100) if tot else 50.0
    _text(draw, (rc0 + 18, fy + 28), 'BUYS / SELLS', sans('Bold', 14), LABEL, 'ls')
    bf = mono('Bold', 26)
    bt, st = str(buys), str(sells)   # the app shows them without separators
    _text(draw, (rc0 + 18, fy + 60), bt, bf, GREEN, 'ls')
    sw_ = draw.textlength(bt, font=bf) / S
    _text(draw, (rc0 + 18 + sw_ + 8, fy + 60), '/', bf, TEXT, 'ls')
    _text(draw, (rc0 + 18 + sw_ + 34, fy + 60), st, bf, RED, 'ls')
    pf = mono('Bold', 17)
    pct_s, pct_b = f'{round(100 - bp)}%', f'{round(bp)}% / '
    _text(draw, (rc1 - 18, fy + 30), pct_s, pf, RED, 'rs')
    _text(draw, (rc1 - 18 - draw.textlength(pct_s, font=pf) / S, fy + 30), pct_b, pf, GREEN, 'rs')
    bx0, bx1 = rc0 + 270, rc1 - 18
    draw.rounded_rectangle(_s(bx0, fy + 46, bx1, fy + 54), radius=4 * S, fill=RED)
    draw.rounded_rectangle(_s(bx0, fy + 46, bx0 + (bx1 - bx0) * bp / 100, fy + 54), radius=4 * S, fill=GREEN)
    cy = fy + 86
    cwid = (rw - 3 * 10) / 4
    for i, (label, v) in enumerate((('5m', card['chg5m']), ('1h', card['chg1h']), ('6h', card['chg6h']), ('24h', card['chg24h']))):
        neg = (v or 0) < 0
        c = RED if neg else GREEN
        bx = rc0 + i * (cwid + 10)
        draw.rounded_rectangle(_s(bx, cy, bx + cwid, cy + 60), radius=11 * S,
                               fill=(33, 22, 24) if neg else (15, 36, 33), outline=(73, 40, 40) if neg else (30, 70, 58), width=S)
        _text(draw, (bx + cwid / 2, cy + 22), label, mono('Bold', 15), (154, 164, 178), 'mm')
        _text(draw, (bx + cwid / 2, cy + 44), fmt_pct(v), _fit(draw, fmt_pct(v), mono, 'Bold', 18, cwid - 12, 11), c, 'mm')
    by_ = cy + 72
    bh = y1 - 24 - by_
    ctaw = 190
    _panel(draw, (rc0, by_, rc1 - ctaw - 10, by_ + bh), fill=PAIR_BG)
    _text(draw, (rc0 + 18, by_ + bh / 2), 'PAIR', sans('Medium', 15), (141, 152, 167), 'lm')
    _text(draw, (rc0 + 70, by_ + bh / 2), short_pair(card['pair']), mono('Medium', 17), (217, 222, 230), 'lm')
    cx0 = rc1 - ctaw
    draw.rounded_rectangle(_s(cx0, by_, rc1, by_ + bh), radius=12 * S, fill=(40, 33, 21), outline=(198, 150, 72), width=2 * S)
    _text(draw, ((cx0 + rc1) / 2, by_ + bh / 2), 'View Token ›', sans('ExtraBold', 20), (247, 194, 104), 'mm')

    out = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_post(d, post_id, live=True):
    """PNG bytes of the token card for post p<id>, or None if it has none."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(post_id)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    c = post_chart_data(d, post_id)
    if not c:
        return None
    card = card_data(d, c, live=live)
    png = render(card, _fetch_image(d, card.get('banner')), _fetch_image(d, card.get('image')))
    with _cache_lock:
        _cache[post_id] = (now, png)
        if len(_cache) > 200:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:50]:
                _cache.pop(k, None)
    return png


def install(d):
    if getattr(d, '_orca_share_token_card_installed', False):
        return
    d._orca_share_token_card_installed = True
    original = d._render_trade_card_png

    def _render_trade_card_png(id):
        # Token posts get the app's token card; trade posts keep their card.
        if isinstance(id, str) and id.startswith('p'):
            try:
                png = render_post(d, id)
                if png:
                    return png
            except Exception as e:
                print(f'[share-token-card] render failed for {id}: {type(e).__name__}: {e}', flush=True)
        return original(id)

    d._render_trade_card_png = _render_trade_card_png
