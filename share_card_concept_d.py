"""Approved Concept D v2 share-card renderer for OrcAgent X token/trade shares.

Keeps the existing 1200x630 banner lookup, X media upload and canonical post
link pipeline intact; only the visual composition is replaced.
"""
import os
from PIL import Image, ImageDraw, ImageFont

_GOLD = (247, 185, 85)
_GOLD2 = (255, 211, 119)
_WHITE = (245, 246, 248)
_MUTED = (168, 174, 184)
_GREEN = (62, 234, 143)
_RED = (255, 91, 111)


def _font(dm, bold, size):
    candidates = []
    if bold:
        candidates += [
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        ]
    else:
        candidates += [
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return dm._tc_font(bold, size)


def _fmt_price(p):
    p = float(p or 0)
    if not p:
        return '—'
    if p < 0.000001:
        return f'${p:.10f}'.rstrip('0').rstrip('.')
    if p < 0.001:
        return f'${p:.8f}'.rstrip('0').rstrip('.')
    if p < 1:
        return f'${p:.6f}'.rstrip('0').rstrip('.')
    return f'${p:,.4f}'.rstrip('0').rstrip('.')


def _fit(draw, text, xy, max_w, dm, bold=True, start=52, minimum=24, fill=_WHITE):
    x, y = xy
    size = start
    while size >= minimum:
        f = _font(dm, bold, size)
        bb = draw.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= max_w:
            draw.text((x, y), text, font=f, fill=fill)
            return f
        size -= 2
    f = _font(dm, bold, minimum)
    draw.text((x, y), text, font=f, fill=fill)
    return f


def _overlay(img):
    return Image.new('RGBA', img.size, (0, 0, 0, 0))


def _draw_brand(draw, dm, W):
    # Larger, cleaner OrcAgent header inspired by the approved Concept D v2.
    draw.rounded_rectangle([42, 34, 103, 95], radius=17, fill=_GOLD2)
    draw.polygon([(73, 49), (57, 82), (89, 82)], fill=(7, 10, 13))
    draw.text((123, 35), 'OrcAgent', font=_font(dm, True, 40), fill=_WHITE)
    draw.text((125, 78), 'TRADE SMARTER', font=_font(dm, False, 13), fill=(205, 188, 156))
    draw.text((125, 97), 'TOGETHER', font=_font(dm, False, 13), fill=(205, 188, 156))

    draw.text((930, 43), 'MEMES MOVE', font=_font(dm, True, 14), fill=_GOLD2)
    draw.text((930, 64), 'FASTER HERE', font=_font(dm, True, 14), fill=_GOLD2)
    draw.text((1091, 53), '→', font=_font(dm, True, 30), fill=_GOLD2)


def _draw_chart_line(draw, pct):
    # Decorative only; intentionally not presented as historical market data.
    col = _GOLD2 if pct >= 0 else (221, 112, 118)
    if pct >= 0:
        pts = [(824, 431), (865, 399), (903, 422), (946, 365), (984, 383), (1034, 323), (1079, 344), (1132, 276)]
    else:
        pts = [(824, 315), (865, 342), (903, 326), (946, 378), (984, 362), (1034, 417), (1079, 397), (1132, 450)]
    draw.line(pts, fill=col, width=4, joint='curve')
    x, y = pts[-1]
    draw.line([(x - 12, y + (12 if pct >= 0 else -12)), (x, y), (x - 16, y + (3 if pct >= 0 else -3))], fill=col, width=4)


def _draw_common(dm, img, symbol, price, pct, mode='CHART', entry_price=None, pnl_value=None, pnl_currency='SOL'):
    W, H = img.size
    pct = float(pct or 0)
    pct_col = _GREEN if pct >= 0 else _RED
    mode = (mode or 'CHART').upper()

    # Approved v2 composition: keep artwork prominent, but build a stable dark
    # information zone at left and a clean footer. A subtle full-frame scrim
    # keeps bright token banners from fighting the interface.
    lay = _overlay(img)
    ld = ImageDraw.Draw(lay)
    ld.rectangle([0, 0, W, H], fill=(4, 7, 11, 72))
    ld.rectangle([0, 0, W, 124], fill=(4, 7, 11, 212))
    ld.rectangle([0, 495, W, H], fill=(4, 7, 11, 230))
    for x in range(0, 560):
        alpha = int(205 - 105 * (x / 560.0))
        ld.line([(x, 120), (x, 494)], fill=(4, 7, 11, alpha))
    img.paste(lay, (0, 0), lay)

    draw = ImageDraw.Draw(img)

    # Refined gold frame, intentionally thinner than v1.
    draw.rounded_rectangle([24, 22, W - 24, H - 22], radius=30, outline=_GOLD, width=2)
    draw.rounded_rectangle([29, 27, W - 29, H - 27], radius=26, outline=(83, 61, 31), width=1)
    _draw_brand(draw, dm, W)

    # Left dark panel: compact and strongly readable over any token banner.
    panel = _overlay(img)
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([48, 146, 470, 425], radius=24, fill=(5, 8, 12, 218), outline=(138, 97, 43, 205), width=2)
    img.paste(panel, (0, 0), panel)
    draw = ImageDraw.Draw(img)

    badge_col = _GOLD2 if mode == 'CHART' else (_GREEN if mode == 'BUY' else _RED)
    badge_w = 126 if mode == 'CHART' else 116
    draw.rounded_rectangle([72, 168, 72 + badge_w, 207], radius=19, outline=badge_col, width=2)
    badge_font = _font(dm, True, 18)
    bb = draw.textbbox((0, 0), mode, font=badge_font)
    draw.text((72 + (badge_w - (bb[2]-bb[0]))/2, 177), mode, font=badge_font, fill=badge_col)

    sym = '$' + str(symbol or 'TOKEN')
    _fit(draw, sym, (72, 220), 360, dm, True, 61, 30, _WHITE)

    if mode == 'CHART':
        draw.text((73, 314), 'PRICE', font=_font(dm, True, 14), fill=(207, 174, 117))
        _fit(draw, _fmt_price(price), (72, 337), 360, dm, True, 39, 26, _WHITE)
    else:
        draw.text((73, 314), 'PRICE', font=_font(dm, True, 14), fill=(207, 174, 117))
        draw.text((288, 314), 'ENTRY', font=_font(dm, True, 14), fill=(207, 174, 117))
        _fit(draw, _fmt_price(price), (72, 339), 190, dm, True, 34, 23, _WHITE)
        _fit(draw, _fmt_price(entry_price), (288, 339), 150, dm, True, 28, 20, _WHITE)
        draw.line([(270, 312), (270, 379)], fill=(95, 98, 106), width=1)
        pnl = float(pnl_value or 0)
        sign = '+' if pnl >= 0 else ''
        pnl_col = _GREEN if pnl >= 0 else _RED
        _fit(draw, f'{sign}{pnl:.4f} {pnl_currency}', (73, 389), 350, dm, True, 22, 16, pnl_col)

    # Large performance figure right. Give it breathing room and cleaner label.
    pct_sign = '+' if pct >= 0 else ''
    pct_text = f'{pct_sign}{pct:.2f}%'
    pct_font = _font(dm, True, 82)
    bb = draw.textbbox((0, 0), pct_text, font=pct_font)
    pw = bb[2] - bb[0]
    px = max(650, W - 70 - pw)
    pbg = _overlay(img)
    pbd = ImageDraw.Draw(pbg)
    pbd.rounded_rectangle([px - 22, 162, W - 48, 294], radius=26, fill=(4, 8, 12, 158))
    img.paste(pbg, (0, 0), pbg)
    draw = ImageDraw.Draw(img)
    _fit(draw, pct_text, (px, 176), W - px - 62, dm, True, 82, 48, pct_col)
    label = 'TRADE PERFORMANCE' if mode != 'CHART' else '24H PERFORMANCE'
    draw.text((px + 4, 263), label, font=_font(dm, True, 14), fill=(210, 213, 218))

    _draw_chart_line(draw, pct)

    # Cleaner footer from approved v2: direct post route in the image, plus CTA.
    draw.line([(49, 494), (W - 49, 494)], fill=(104, 75, 35), width=1)
    draw.ellipse([55, 522, 100, 567], outline=_GOLD2, width=2)
    draw.polygon([(77, 531), (65, 554), (89, 554)], fill=_GOLD2)
    draw.text((121, 515), 'OrcAgent', font=_font(dm, True, 22), fill=_WHITE)
    draw.text((121, 545), 'Trade smarter. Together.', font=_font(dm, False, 14), fill=_MUTED)

    # The actual post id is not available inside the low-level renderer; the
    # real clickable canonical /post/p... URL is always included in the tweet.
    draw.text((455, 532), 'orcagent.fun/post/…', font=_font(dm, False, 20), fill=(194, 198, 207))

    draw.rounded_rectangle([835, 515, 1135, 570], radius=27, fill=_GOLD2)
    draw.text((879, 530), 'VIEW ON ORCAGENT', font=_font(dm, True, 18), fill=(10, 12, 14))
    draw.text((1096, 525), '→', font=_font(dm, True, 29), fill=(10, 12, 14))

    draw.text((52, 591), 'OrcAgent.fun', font=_font(dm, True, 15), fill=_GOLD2)
    draw.text((493, 594), 'TRADE SMARTER. TOGETHER.', font=_font(dm, False, 11), fill=(153, 145, 129))


def install(dm):
    if getattr(dm, '_orca_concept_d_share_card_installed', False):
        return
    dm._orca_concept_d_share_card_installed = True

    def _concept_d_chart(img, symbol, price, chg24h):
        _draw_common(dm, img, symbol, float(price or 0), float(chg24h or 0), mode='CHART')

    def _concept_d_trade(img, symbol, side, entry_price, exit_price, pnl_pct, pnl_sol, pnl_currency='SOL'):
        _draw_common(
            dm, img, symbol, float(exit_price or entry_price or 0), float(pnl_pct or 0),
            mode=(side or 'BUY').upper(), entry_price=float(entry_price or 0),
            pnl_value=float(pnl_sol or 0), pnl_currency=pnl_currency or 'SOL'
        )

    # Existing generator calls resolve these globals dynamically, so this
    # upgrades /api/trade-card/<id>.png, unfurls and X media uploads together.
    dm._tc_draw_chart_content = _concept_d_chart
    dm._tc_draw_content = _concept_d_trade
