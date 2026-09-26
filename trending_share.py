"""Share the home feed's "Trending" card on X (and anywhere else).

  GET /trending/<chain>/<token>             the link people share
  GET /api/trending-card/<chain>/<token>.png  the 1200x630 image X shows

The link is a small public page whose Open Graph / X card tags carry the
token's live numbers and an image drawn like the in-app Trending card: the
OrcAgent header with the TRENDING tag, the token, its price and 24h change,
the price line, buy pressure, buys / 24h volume / sells, and "Trade $X".
A person who opens the link is sent on into the app: to the Trending card
on the home feed while the token is still trending, otherwise to the token
on Live Market.

Numbers are the hero's own while it is the current Trending token, else the
pair's live DexScreener row. The price line uses the app's own chart
candles, or the pair's real -24h/-6h/-1h/-5m/now prices when there are none
(never invented). Logos pass the app's SSRF check (share_token_card). PNGs
are cached for a few minutes.
"""
from __future__ import annotations

import html
import io
import json
import re
import threading
import time
from urllib.parse import quote

from flask import Response, abort, redirect, request
from PIL import Image, ImageDraw, ImageFilter

import share_token_card as stc
import trending_hero as th

W, H, S = 1200, 630, 2
BG = (8, 11, 16)
CARD, CARD_BORDER = (16, 21, 28), (38, 46, 58)
TILE = (22, 28, 37)
TEXT, SUB, MUTED = (243, 245, 248), (199, 204, 212), (139, 150, 163)
GOLD, GOLD2 = (247, 185, 85), (255, 211, 106)
GREEN, RED = (95, 211, 155), (240, 113, 120)
CHAIN_NAMES = {'solana': 'Solana', 'bsc': 'BNB Chain', 'base': 'Base', 'arbitrum': 'Arbitrum',
               'polygon': 'Polygon', 'robinhood': 'Robinhood Chain'}
CHAIN_BADGE = {'solana': ('S', (153, 69, 255)), 'bsc': ('B', (240, 185, 11)), 'base': ('B', (0, 82, 255)),
               'arbitrum': ('A', (40, 160, 240)), 'polygon': ('P', (130, 71, 229)),
               'robinhood': ('R', (0, 200, 5))}
_SOL_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
_EVM_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
CACHE_SECONDS = 300

_cache: dict = {}
_cache_lock = threading.Lock()


def valid(chain: str, token: str) -> bool:
    if chain not in CHAIN_NAMES:
        return False
    return bool((_SOL_RE if chain == 'solana' else _EVM_RE).match(token or ''))


def share_path(chain: str, token: str) -> str:
    return f'/trending/{chain}/{token}'


# ── data ────────────────────────────────────────────────────────────────
def snapshot(d, chain: str, token: str):
    """The token's card numbers: the live hero's while it is the hero, else
    the pair's live DexScreener row. None when nothing is known."""
    try:
        hero = th.current_hero(d)
    except Exception:
        hero = None
    if hero and hero.get('mint') == token and hero.get('chain') == chain:
        return dict(hero, is_hero=True)
    p = stc._live_pair(d, {'mint': token, 'chain': chain})
    if not p or not stc._num(p.get('priceUsd')):
        return None
    tx = (p.get('txns') or {}).get('h24') or {}
    base = p.get('baseToken') or {}
    return {
        'mint': token, 'chain': chain, 'symbol': base.get('symbol') or '', 'name': base.get('name') or '',
        'pair_address': p.get('pairAddress') or '', 'image_url': (p.get('info') or {}).get('imageUrl') or '',
        'price_usd': stc._num(p.get('priceUsd')) or 0,
        'price_change_24h': stc._num((p.get('priceChange') or {}).get('h24')) or 0,
        'volume_24h': stc._num((p.get('volume') or {}).get('h24')) or 0,
        'buys_24h': int(stc._num(tx.get('buys')) or 0), 'sells_24h': int(stc._num(tx.get('sells')) or 0),
        '_changes': p.get('priceChange') or {}, 'is_hero': False,
    }


def price_points(d, t) -> list:
    """Closing prices for the line: the app's own 5m chart candles, else the
    pair's real prices at -24h/-6h/-1h/-5m/now."""
    try:
        view = d.app.view_functions.get('api_chart')
        if view:
            qs = 'tf=5m&chain=' + quote(t['chain']) + ('&pair=' + quote(t['pair_address']) if t.get('pair_address') else '')
            with d.app.test_request_context('/api/chart/' + t['mint'] + '?' + qs):
                resp = view(t['mint'])
            data = resp.get_json() if hasattr(resp, 'get_json') else None
            closes = [float(c.get('c') or 0) for c in (data or {}).get('candles') or []]
            closes = [c for c in closes if c > 0][-40:]
            price = float(t.get('price_usd') or 0)
            # Same guard as the app: candles 10x away from the live price are
            # the other side of the pool, not this token.
            if len(closes) >= 2 and price and 0.1 < closes[-1] / price < 10:
                return closes
    except Exception:
        pass
    ch = t.get('_changes') or {}
    return stc.spark_points(float(t.get('price_usd') or 0), stc._num(t.get('price_change_24h')),
                            stc._num(ch.get('h6')), stc._num(ch.get('h1')), stc._num(ch.get('m5')))


def fmt_price(n) -> str:
    n = float(n or 0)
    if n >= 1:
        return '$' + f'{n:,.2f}'
    if n >= 0.01:
        return '$' + f'{n:.4f}'
    if n <= 0:
        return '$0'
    import math
    dec = min(10, 2 - math.floor(math.log10(n)))
    return '$' + f'{n:.{dec}f}'


def fmt_usd(n) -> str:
    n = float(n or 0)
    if n >= 1e9:
        return f'${n / 1e9:.2f}B'
    if n >= 1e6:
        return f'${n / 1e6:.2f}M'
    if n >= 1e3:
        return f'${round(n / 1e3)}K'
    return f'${round(n)}'


def fmt_pct(n) -> str:
    n = float(n or 0)
    return ('+' if n >= 0 else '') + f'{n:.1f}%'


def texts(t) -> tuple:
    """(title, description) for the card and the share text."""
    sym = '$' + (t.get('symbol') or '?')
    chain = CHAIN_NAMES.get(t.get('chain'), 'crypto')
    title = f'{sym} is trending on {chain} 🔥 {fmt_pct(t.get("price_change_24h"))} in 24h'
    buys, sells = int(t.get('buys_24h') or 0), int(t.get('sells_24h') or 0)
    buy_pct = round(100 * buys / (buys + sells)) if buys + sells else 50
    desc = (f'{fmt_usd(t.get("volume_24h"))} volume · {buy_pct}% buy pressure · '
            f'price {fmt_price(t.get("price_usd"))}. Vote bullish or bearish and trade it on OrcAgent.')
    return title, desc


# ── drawing ─────────────────────────────────────────────────────────────
def _s(*v):
    return tuple(int(round(x * S)) for x in v)


def _flame(draw, cx, cy, size, fill):
    """A small flame, drawn (the fonts carry no emoji)."""
    r = size / 2
    pts = [(cx, cy - r), (cx + r * .55, cy - r * .1), (cx + r * .62, cy + r * .38), (cx + r * .3, cy + r * .78),
           (cx, cy + r * .88), (cx - r * .3, cy + r * .78), (cx - r * .62, cy + r * .38), (cx - r * .5, cy),
           (cx - r * .12, cy - r * .3)]
    draw.polygon([_s(x, y) for x, y in pts], fill=fill)


def _tick(draw, cx, cy, r):
    draw.ellipse(_s(cx - r, cy - r, cx + r, cy + r), fill=GOLD)
    draw.line([_s(cx - r * .45, cy + r * .02), _s(cx - r * .1, cy + r * .38), _s(cx + r * .48, cy - r * .32)],
              fill=BG, width=int(r * .42 * S), joint='curve')


def _arrow(draw, x, cy, size, fill):
    draw.line([_s(x, cy), _s(x + size, cy)], fill=fill, width=int(2.6 * S))
    draw.line([_s(x + size * .55, cy - size * .42), _s(x + size, cy), _s(x + size * .55, cy + size * .42)],
              fill=fill, width=int(2.6 * S), joint='curve')


def render(t, points, logo_img=None) -> bytes:
    img = Image.new('RGB', _s(W, H), BG)
    glow = Image.new('RGB', img.size, BG)
    ImageDraw.Draw(glow).ellipse(_s(-220, -300, 520, 300), fill=(44, 34, 16))
    img = glow.filter(ImageFilter.GaussianBlur(90 * S))
    d = ImageDraw.Draw(img)
    sans, mono = stc.sans, stc.mono

    # ── header: the post author line ──
    d.rounded_rectangle(_s(48, 40, 104, 96), radius=18 * S, fill=GOLD)
    d.polygon([_s(76, 55), _s(62, 80), _s(90, 80)], fill=BG)
    d.text(_s(120, 68), 'OrcAgent', font=sans('ExtraBold', 30), fill=TEXT, anchor='lm')
    nx = 120 + d.textlength('OrcAgent', font=sans('ExtraBold', 30)) / S
    _tick(d, nx + 20, 68, 12)
    px = nx + 44
    label = 'SURGING' if t.get('surging') else 'TRENDING'
    lw = d.textlength(label, font=sans('ExtraBold', 17)) / S
    d.rounded_rectangle(_s(px, 50, px + lw + 54, 86), radius=18 * S, fill=(52, 40, 20))
    _flame(d, px + 21, 68, 18, GOLD)
    d.text(_s(px + 36, 68), label, font=sans('ExtraBold', 17), fill=GOLD, anchor='lm')
    d.ellipse(_s(1062, 61, 1076, 75), fill=GREEN)
    d.text(_s(1086, 68), 'LIVE', font=sans('ExtraBold', 18), fill=MUTED, anchor='lm')

    # ── left: the token ──
    sym = t.get('symbol') or '?'
    chain = t.get('chain') or 'solana'
    d.ellipse(_s(48, 132, 160, 244), fill=(20, 26, 33), outline=GOLD, width=3 * S)
    if logo_img is not None:
        logo = stc._cover(logo_img, 104 * S, 104 * S)
        mask = Image.new('L', logo.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, logo.width - 1, logo.height - 1), fill=255)
        img.paste(logo, _s(52, 136), mask)
    else:
        d.text(_s(104, 188), sym[:1].upper(), font=sans('ExtraBold', 48), fill=GOLD, anchor='mm')
    letter, color = CHAIN_BADGE.get(chain, ('?', (90, 90, 90)))
    d.rounded_rectangle(_s(126, 208, 162, 244), radius=10 * S, fill=color, outline=BG, width=3 * S)
    d.text(_s(144, 226), letter, font=sans('ExtraBold', 18), fill=(255, 255, 255), anchor='mm')

    sf = stc._fit(d, '$' + sym, sans, 'ExtraBold', 64, 420)
    d.text(_s(186, 186), '$' + sym, font=sf, fill=TEXT, anchor='ls')
    name = (t.get('name') or sym)
    d.text(_s(188, 226), (name[:28] + ('…' if len(name) > 28 else '')) + ' · ' + CHAIN_NAMES.get(chain, chain),
           font=sans('Medium', 22), fill=MUTED, anchor='ls')

    pf = stc._fit(d, fmt_price(t.get('price_usd')), mono, 'ExtraBold', 70, 540)
    d.text(_s(48, 340), fmt_price(t.get('price_usd')), font=pf, fill=TEXT, anchor='ls')
    chg = float(t.get('price_change_24h') or 0)
    up = chg >= 0
    col = GREEN if up else RED
    cf = mono('ExtraBold', 26)
    ct = ('▲ ' if up else '▼ ') + fmt_pct(chg)
    cw = d.textlength(ct, font=cf) / S
    d.rounded_rectangle(_s(48, 364, 48 + cw + 32, 408), radius=12 * S,
                        fill=(20, 52, 40) if up else (58, 24, 30))
    d.text(_s(64, 386), ct, font=cf, fill=col, anchor='lm')
    d.text(_s(48 + cw + 48, 386), 'in 24h', font=sans('Medium', 22), fill=MUTED, anchor='lm')

    d.text(_s(48, 462), 'Trending on ' + CHAIN_NAMES.get(chain, chain) + ' with',
           font=sans('Medium', 26), fill=SUB, anchor='ls')
    d.text(_s(48, 500), fmt_usd(t.get('volume_24h')) + ' volume in 24h.', font=sans('Medium', 26), fill=SUB, anchor='ls')
    d.text(_s(48, 584), 'orcagent.fun', font=mono('ExtraBold', 24), fill=GOLD, anchor='ls')

    # ── right: the card ──
    L, T, R, B = 640, 124, 1152, 590
    d.rounded_rectangle(_s(L, T, R, B), radius=26 * S, fill=CARD, outline=CARD_BORDER, width=int(1.5 * S))
    cl, cr, ct_, cb = L + 28, R - 28, T + 30, T + 196
    pts = [p for p in (points or []) if p and p > 0]
    if len(pts) >= 2:
        lo, hi = min(pts), max(pts)
        if hi == lo:
            hi, lo = hi * 1.01, lo * 0.99
        xy = [(cl + (cr - cl) * i / (len(pts) - 1), ct_ + 8 + (1 - (v - lo) / (hi - lo)) * (cb - ct_ - 16))
              for i, v in enumerate(pts)]
        fill = Image.new('RGBA', img.size, (0, 0, 0, 0))
        ImageDraw.Draw(fill).polygon([_s(x, y) for x, y in xy] + [_s(cr, cb), _s(cl, cb)], fill=col + (46,))
        img.paste(fill, (0, 0), fill)
        d = ImageDraw.Draw(img)
        d.line([_s(x, y) for x, y in xy], fill=col, width=int(3.2 * S), joint='curve')
        lx, ly = xy[-1]
        d.ellipse(_s(lx - 6, ly - 6, lx + 6, ly + 6), fill=col)

    buys, sells = int(t.get('buys_24h') or 0), int(t.get('sells_24h') or 0)
    bp = round(100 * buys / (buys + sells)) if buys + sells else 50
    lf = mono('Bold', 15)
    d.text(_s(cl, T + 236), 'BUY PRESSURE', font=lf, fill=MUTED, anchor='ls')
    right = f'{bp}% buy · {100 - bp}% sell'
    rw = d.textlength(right, font=lf) / S
    d.text(_s(cr - rw, T + 236), f'{bp}% buy', font=lf, fill=GREEN, anchor='ls')
    d.text(_s(cr, T + 236), f'{100 - bp}% sell', font=lf, fill=RED, anchor='rs')
    d.text(_s(cr - rw + d.textlength(f'{bp}% buy', font=lf) / S, T + 236), ' · ', font=lf, fill=MUTED, anchor='ls')
    d.rounded_rectangle(_s(cl, T + 250, cr, T + 262), radius=6 * S, fill=RED)
    if bp > 0:
        d.rounded_rectangle(_s(cl, T + 250, cl + (cr - cl) * bp / 100, T + 262), radius=6 * S, fill=GREEN)

    tw = (cr - cl - 20) / 3
    for i, (val, lab, c) in enumerate(((f'{buys:,}', 'BUYS', GREEN), (fmt_usd(t.get('volume_24h')), 'VOL · 24H', TEXT),
                                       (f'{sells:,}', 'SELLS', RED))):
        x = cl + i * (tw + 10)
        d.rounded_rectangle(_s(x, T + 282, x + tw, T + 364), radius=14 * S, fill=TILE)
        vf = stc._fit(d, val, mono, 'ExtraBold', 28, tw - 16)
        d.text(_s(x + tw / 2, T + 322), val, font=vf, fill=c, anchor='ms')
        d.text(_s(x + tw / 2, T + 348), lab, font=sans('ExtraBold', 13), fill=MUTED, anchor='ms')

    d.rounded_rectangle(_s(cl, T + 384, cr, T + 440), radius=16 * S, fill=GOLD2)
    btn = 'Trade $' + sym
    bf = stc._fit(d, btn, sans, 'ExtraBold', 24, cr - cl - 80)
    bw = d.textlength(btn, font=bf) / S
    bx = (cl + cr) / 2 - (bw + 30) / 2
    d.text(_s(bx, T + 412), btn, font=bf, fill=(17, 19, 24), anchor='lm')
    _arrow(d, bx + bw + 12, T + 412, 18, (17, 19, 24))

    out = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format='PNG', optimize=True)
    return buf.getvalue()


def render_token(d, chain, token):
    key = (chain, token)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    t = snapshot(d, chain, token)
    if not t:
        return None
    png = render(t, price_points(d, t), stc._fetch_image(d, t.get('image_url')))
    with _cache_lock:
        _cache[key] = (now, png)
        if len(_cache) > 200:
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:50]:
                _cache.pop(k, None)
    return png


# ── the share page ──────────────────────────────────────────────────────
def page_html(t, chain, token, base='https://orcagent.fun') -> str:
    esc = lambda s: html.escape(str(s), quote=True)
    bucket = int(time.time() // CACHE_SECONDS)
    if t:
        title, desc = texts(t)
        image = f'{base}/api/trending-card/{chain}/{token}.png?v={bucket}'
        alt = f'${t.get("symbol") or "?"} trending on OrcAgent'
        target = '/?trending=1#trending' if t.get('is_hero') else '/live-market?mint=' + quote(token)
    else:
        title, desc = 'Trending on OrcAgent', 'Discover trending tokens, vote bullish or bearish and trade across chains with USDC.'
        image, alt, target = base + '/static/og-orcagent.png', 'OrcAgent', '/live-market?mint=' + quote(token)
    url = base + share_path(chain, token)
    tags = [
        f'<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="OrcAgent">',
        f'<meta property="og:title" content="{esc(title)}">',
        f'<meta property="og:description" content="{esc(desc)}">',
        f'<meta property="og:url" content="{esc(url)}">',
        f'<meta property="og:image" content="{esc(image)}">',
        f'<meta property="og:image:secure_url" content="{esc(image)}">',
        '<meta property="og:image:type" content="image/png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{esc(alt)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<meta name="twitter:site" content="@Orcagent">',
        f'<meta name="twitter:title" content="{esc(title)}">',
        f'<meta name="twitter:description" content="{esc(desc)}">',
        f'<meta name="twitter:image" content="{esc(image)}">',
        f'<meta name="twitter:image:alt" content="{esc(alt)}">',
    ]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">\n' + '\n'.join(tags) + '\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title>'
            '<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;'
            'background:#080b10;color:#f3f5f8;font:600 16px/1.5 system-ui,-apple-system,sans-serif}'
            'a{color:#f7b955}</style></head><body>'
            f'<p>Opening on OrcAgent… <a href="{esc(target)}">Continue</a></p>'
            f'<script>location.replace({json.dumps(target)});</script>'
            '</body></html>')


def install(d):
    app = d.app
    if getattr(app, '_orca_trending_share_installed', False):
        return
    app._orca_trending_share_installed = True

    @app.get('/trending/<chain>/<token>')
    @d.rate_limit(60, 60)
    def trending_share_page(chain, token):
        chain = (chain or '').lower()
        if not valid(chain, token):
            abort(404)
        try:
            t = snapshot(d, chain, token)
        except Exception:
            t = None
        resp = Response(page_html(t, chain, token), mimetype='text/html')
        resp.headers['Cache-Control'] = 'public, max-age=300'
        return resp

    @app.get('/api/trending-card/<chain>/<token>.png')
    @d.rate_limit(60, 60)
    def trending_share_card(chain, token):
        chain = (chain or '').lower()
        if not valid(chain, token):
            abort(404)
        try:
            png = render_token(d, chain, token)
        except Exception as e:
            print(f'[trending-share] render failed for {chain}/{token[:10]}: {type(e).__name__}: {e}', flush=True)
            png = None
        if not png:
            return redirect('/static/og-orcagent.png', code=302)
        resp = Response(png, mimetype='image/png')
        resp.headers['Cache-Control'] = 'public, max-age=300'
        return resp
