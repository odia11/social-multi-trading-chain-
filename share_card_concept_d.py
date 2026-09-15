"""Approved premium share-card renderer for OrcAgent X token/trade shares.

Keeps the existing 1200x630 banner lookup, media upload and permalink pipeline
intact; only the visual composition is replaced. All visible copy is English.
"""
import os
from PIL import Image, ImageDraw, ImageFont

_GOLD = (247, 185, 85)
_GOLD2 = (255, 204, 86)
_WHITE = (248, 249, 251)
_MUTED = (166, 174, 187)
_GREEN = (55, 231, 132)
_RED = (255, 92, 111)
_DARK = (5, 9, 14)


def _font(dm, bold, size):
    candidates = (
        ['/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
         '/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
        if bold else
        ['/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
         '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return dm._tc_font(bold, size)


def _fmt_price(value):
    p = float(value or 0)
    if not p:
        return '—'
    if p < 0.000001:
        return f'${p:.10f}'.rstrip('0').rstrip('.')
    if p < 0.001:
        return f'${p:.8f}'.rstrip('0').rstrip('.')
    if p < 1:
        return f'${p:.6f}'.rstrip('0').rstrip('.')
    return f'${p:,.4f}'.rstrip('0').rstrip('.')


def _fit(draw, text, xy, max_w, dm, bold=True, start=52, minimum=22, fill=_WHITE):
    x, y = xy
    for size in range(start, minimum - 1, -2):
        font = _font(dm, bold, size)
        bb = draw.textbbox((0, 0), str(text), font=font)
        if bb[2] - bb[0] <= max_w:
            draw.text((x, y), str(text), font=font, fill=fill)
            return font
    font = _font(dm, bold, minimum)
    draw.text((x, y), str(text), font=font, fill=fill)
    return font


def _overlay(img):
    return Image.new('RGBA', img.size, (0, 0, 0, 0))


def _draw_brand(draw, dm):
    draw.rounded_rectangle([43, 35, 102, 94], radius=16, fill=_GOLD2)
    draw.polygon([(72, 48), (56, 81), (89, 81)], fill=(6, 10, 14))
    draw.text((122, 34), 'OrcAgent', font=_font(dm, True, 39), fill=_WHITE)
    draw.text((124, 79), 'TRADE SMARTER', font=_font(dm, False, 13), fill=(201, 190, 168))
    draw.text((124, 98), 'TOGETHER', font=_font(dm, False, 13), fill=(201, 190, 168))

    draw.text((930, 42), 'MEMES MOVE', font=_font(dm, True, 14), fill=_GOLD2)
    draw.text((930, 63), 'FASTER HERE', font=_font(dm, True, 14), fill=_GOLD2)
    draw.text((1095, 49), '→', font=_font(dm, True, 31), fill=_GOLD2)


def _draw_chart_line(draw, pct):
    col = _GOLD2 if pct >= 0 else _RED
    if pct >= 0:
        pts = [(550, 439), (608, 421), (654, 440), (702, 399), (752, 416),
               (799, 379), (849, 397), (899, 354), (951, 370), (1005, 321),
               (1060, 339), (1128, 280)]
    else:
        pts = [(550, 307), (608, 330), (654, 316), (702, 351), (752, 339),
               (799, 378), (849, 362), (899, 404), (951, 389), (1005, 432),
               (1060, 414), (1128, 458)]
    draw.line(pts, fill=col, width=5, joint='curve')
    x, y = pts[-1]
    draw.ellipse([x-6, y-6, x+6, y+6], fill=col)


def _draw_common(dm, img, symbol, price, pct, mode='CHART', entry_price=None,
                 pnl_value=None, pnl_currency='SOL'):
    W, H = img.size
    pct = float(pct or 0)
    pct_col = _GREEN if pct >= 0 else _RED
    mode = (mode or 'CHART').upper()

    # Dark cinematic treatment while preserving the token/banner artwork.
    layer = _overlay(img)
    ld = ImageDraw.Draw(layer)
    ld.rectangle([0, 0, W, H], fill=(2, 6, 11, 74))
    ld.rectangle([0, 0, W, 126], fill=(2, 6, 11, 210))
    ld.rectangle([0, 477, W, H], fill=(2, 6, 11, 235))
    for x in range(0, 520):
        alpha = int(222 - 112 * (x / 520.0))
        ld.line([(x, 120), (x, 478)], fill=(3, 7, 12, alpha))
    img.paste(layer, (0, 0), layer)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([21, 20, W-21, H-20], radius=31, outline=_GOLD, width=2)
    draw.rounded_rectangle([26, 25, W-26, H-25], radius=27, outline=(87, 62, 30), width=1)
    _draw_brand(draw, dm)

    # Left market panel.
    glass = _overlay(img)
    gd = ImageDraw.Draw(glass)
    gd.rounded_rectangle([47, 145, 476, 423], radius=25,
                         fill=(4, 8, 13, 221), outline=(158, 111, 48, 215), width=2)
    img.paste(glass, (0, 0), glass)
    draw = ImageDraw.Draw(img)

    badge_col = _GOLD2 if mode == 'CHART' else (_GREEN if mode == 'BUY' else _RED)
    badge_w = 146 if mode == 'CHART' else 126
    draw.rounded_rectangle([70, 165, 70 + badge_w, 211], radius=22,
                           outline=badge_col, width=2)
    if mode == 'CHART':
        # small chart-bars icon
        draw.rectangle([88, 187, 94, 198], fill=badge_col)
        draw.rectangle([99, 179, 105, 198], fill=badge_col)
        draw.rectangle([110, 171, 116, 198], fill=badge_col)
        tx = 130
    else:
        tx = 90
    draw.text((tx, 176), mode, font=_font(dm, True, 18), fill=badge_col)

    sym = '$' + str(symbol or 'TOKEN').upper()
    _fit(draw, sym, (70, 224), 370, dm, True, 62, 30, _WHITE)

    if mode == 'CHART':
        draw.text((72, 318), 'PRICE', font=_font(dm, True, 14), fill=(200, 176, 132))
        _fit(draw, _fmt_price(price), (70, 343), 365, dm, True, 42, 25, _WHITE)
    else:
        draw.text((72, 314), 'EXIT PRICE', font=_font(dm, True, 13), fill=(200, 176, 132))
        draw.text((286, 314), 'ENTRY', font=_font(dm, True, 13), fill=(200, 176, 132))
        _fit(draw, _fmt_price(price), (70, 339), 198, dm, True, 32, 20, _WHITE)
        _fit(draw, _fmt_price(entry_price), (286, 339), 160, dm, True, 27, 19, _WHITE)
        draw.line([(270, 314), (270, 381)], fill=(91, 98, 108), width=1)
        pnl = float(pnl_value or 0)
        sign = '+' if pnl >= 0 else ''
        _fit(draw, f'{sign}{pnl:.4f} {pnl_currency}', (71, 389), 355, dm, True, 22, 16,
             _GREEN if pnl >= 0 else _RED)

    # Hero performance on the right.
    sign = '+' if pct >= 0 else ''
    pct_text = f'{sign}{pct:.2f}%'
    _fit(draw, pct_text, (645, 190), 500, dm, True, 84, 46, pct_col)
    perf_label = '24H PERFORMANCE' if mode == 'CHART' else 'TRADE PERFORMANCE'
    draw.text((736, 278), perf_label, font=_font(dm, True, 15), fill=(211, 217, 224))
    _draw_chart_line(draw, pct)

    # Asset/channel strip, intentionally generic so it is correct across chains.
    draw.line([(50, 463), (W-50, 463)], fill=(119, 83, 36), width=1)
    draw.ellipse([58, 479, 99, 520], outline=_GOLD2, width=3)
    draw.line([(69, 500), (87, 500)], fill=_GOLD2, width=3)
    draw.text((121, 485), 'MULTI-CHAIN', font=_font(dm, True, 17), fill=(226, 228, 232))
    draw.line([(430, 482), (430, 518)], fill=(105, 107, 112), width=1)
    draw.text((468, 485), 'orcagent.fun', font=_font(dm, False, 18), fill=(226, 228, 232))

    # Premium CTA footer matching the approved mock.
    draw.line([(50, 531), (W-50, 531)], fill=(119, 83, 36), width=1)
    draw.text((63, 551), 'TRADE SMARTER. TOGETHER.', font=_font(dm, True, 15), fill=_GOLD2)
    draw.text((64, 579), 'MEMES  ×  MARKETS  ×  PEOPLE', font=_font(dm, False, 12), fill=_MUTED)

    draw.rounded_rectangle([790, 548, 1138, 607], radius=29, fill=_GOLD2)
    draw.text((837, 565), 'VIEW ON ORCAGENT', font=_font(dm, True, 19), fill=(8, 10, 13))
    draw.text((1095, 557), '→', font=_font(dm, True, 31), fill=(8, 10, 13))


def install(dm):
    if getattr(dm, '_orca_concept_d_share_card_installed', False):
        return
    dm._orca_concept_d_share_card_installed = True

    def _concept_d_chart(img, symbol, price, chg24h):
        _draw_common(dm, img, symbol, float(price or 0), float(chg24h or 0), mode='CHART')

    def _concept_d_trade(img, symbol, side, entry_price, exit_price, pnl_pct,
                         pnl_sol, pnl_currency='SOL'):
        _draw_common(
            dm, img, symbol, float(exit_price or entry_price or 0), float(pnl_pct or 0),
            mode=(side or 'BUY').upper(), entry_price=float(entry_price or 0),
            pnl_value=float(pnl_sol or 0), pnl_currency=pnl_currency or 'SOL'
        )

    dm._tc_draw_chart_content = _concept_d_chart
    dm._tc_draw_content = _concept_d_trade
