"""Concept D share-card renderer for OrcAgent token/trade shares.

This module replaces the two low-level Pillow overlay functions used by the
existing 1200x630 X media pipeline. The existing banner lookup, SSRF safety,
media upload, post IDs and X posting behavior remain untouched; only the visual
composition changes.
"""
import os
from PIL import Image, ImageDraw, ImageFont

_GOLD = (247, 185, 85)
_GOLD2 = (255, 210, 115)
_WHITE = (244, 246, 248)
_MUTED = (178, 184, 194)
_DARK = (6, 10, 15)
_GREEN = (74, 238, 151)
_RED = (255, 94, 112)


def _font(dm, bold, size):
    # Prefer a broad Unicode system face for symbols such as CJK token names;
    # fall back to OrcAgent's vendored UI font when it is unavailable.
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


def _fit_text(draw, text, x, y, max_w, dm, bold, start_size, min_size, fill):
    size = start_size
    while size > min_size:
        f = _font(dm, bold, size)
        bb = draw.textbbox((0, 0), text, font=f)
        if bb[2] - bb[0] <= max_w:
            draw.text((x, y), text, font=f, fill=fill)
            return f
        size -= 2
    f = _font(dm, bold, min_size)
    draw.text((x, y), text, font=f, fill=fill)
    return f


def _rgba_layer(img):
    return Image.new('RGBA', img.size, (0, 0, 0, 0))


def _draw_common(dm, img, symbol, price, pct, mode='CHART', subline=''):
    W, H = img.size
    pct = float(pct or 0)
    pct_col = _GREEN if pct >= 0 else _RED

    # Keep the real token artwork visible, but build the premium dark/gold
    # Concept D frame around it. The left side receives a heavier scrim for
    # guaranteed text legibility while the center/right art remains readable.
    layer = _rgba_layer(img)
    ld = ImageDraw.Draw(layer)
    ld.rectangle([0, 0, W, H], fill=(4, 7, 11, 96))
    for x in range(0, 610):
        a = int(205 - (115 * (x / 610)))
        ld.line([(x, 0), (x, H)], fill=(4, 7, 11, max(70, a)))
    ld.rectangle([0, 0, W, 116], fill=(4, 7, 11, 198))
    ld.rectangle([0, 498, W, H], fill=(4, 7, 11, 220))
    img.paste(layer, (0, 0), layer)

    draw = ImageDraw.Draw(img)

    # Outer luxury frame + subtle inner line.
    draw.rounded_rectangle([18, 18, W - 18, H - 18], radius=30, outline=_GOLD, width=3)
    draw.rounded_rectangle([24, 24, W - 24, H - 24], radius=26, outline=(92, 70, 34), width=1)

    # Minimal OrcAgent mark (gold tile + black triangle), then branding.
    draw.rounded_rectangle([54, 45, 108, 99], radius=15, fill=_GOLD)
    draw.polygon([(81, 60), (66, 86), (96, 86)], fill=(8, 11, 15))
    draw.text((126, 43), 'OrcAgent', font=_font(dm, True, 38), fill=_WHITE)
    draw.text((128, 84), 'TRADE SMARTER. TOGETHER.', font=_font(dm, False, 13), fill=(189, 171, 137))

    # Top-right Concept D slogan.
    draw.text((900, 49), 'MEMES MOVE', font=_font(dm, True, 15), fill=_GOLD2)
    draw.text((900, 70), 'FASTER HERE  ->', font=_font(dm, True, 15), fill=_GOLD2)

    # Left information panel.
    panel = _rgba_layer(img)
    pd = ImageDraw.Draw(panel)
    pd.rounded_rectangle([46, 150, 445, 425], radius=22, fill=(5, 8, 13, 194), outline=(125, 92, 45, 185), width=2)
    img.paste(panel, (0, 0), panel)
    draw = ImageDraw.Draw(img)

    mode_text = (mode or 'CHART').upper()
    badge_col = _GOLD if mode_text == 'CHART' else (95, 235, 167) if mode_text == 'BUY' else _RED
    draw.rounded_rectangle([70, 174, 165, 210], radius=16, outline=badge_col, width=2)
    draw.text((91, 181), mode_text, font=_font(dm, True, 16), fill=badge_col)

    sym = '$' + str(symbol or 'TOKEN')
    _fit_text(draw, sym, 70, 225, 345, dm, True, 58, 28, _WHITE)
    draw.text((72, 307), 'PRICE', font=_font(dm, True, 14), fill=(194, 160, 104))
    _fit_text(draw, _fmt_price(price), 70, 333, 345, dm, True, 39, 25, _WHITE)

    if subline:
        _fit_text(draw, subline, 70, 386, 345, dm, False, 17, 12, _MUTED)

    # Large performance figure in the right/top visual area.
    pct_sign = '+' if pct >= 0 else ''
    pct_text = f'{pct_sign}{pct:.2f}%'
    # faint dark backing so this remains legible on bright banners.
    bb_font = _font(dm, True, 78)
    bb = draw.textbbox((0, 0), pct_text, font=bb_font)
    pw = bb[2] - bb[0]
    px = max(505, W - 72 - pw)
    perf = _rgba_layer(img)
    pfd = ImageDraw.Draw(perf)
    pfd.rounded_rectangle([px - 22, 170, W - 50, 295], radius=24, fill=(4, 8, 12, 170))
    img.paste(perf, (0, 0), perf)
    draw = ImageDraw.Draw(img)
    _fit_text(draw, pct_text, px, 183, W - px - 68, dm, True, 78, 46, pct_col)
    draw.text((px + 4, 266), '24H PERFORMANCE' if mode_text == 'CHART' else 'TRADE PERFORMANCE',
              font=_font(dm, True, 14), fill=(202, 205, 211))

    # Decorative chart line on the lower right; purely visual, not fake data.
    line_pts = [(770, 427), (815, 385), (855, 407), (900, 347), (943, 369), (995, 300), (1046, 326), (1120, 245)]
    draw.line(line_pts, fill=_GOLD2, width=5, joint='curve')
    for x, y in line_pts[-3:]:
        draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=_GOLD2)

    # Bottom identity + CTA strip. It is visual branding inside the X image;
    # the actual clickable post URL remains in the tweet text.
    draw.ellipse([54, 521, 94, 561], outline=_GOLD, width=2)
    draw.polygon([(74, 530), (64, 549), (84, 549)], fill=_GOLD)
    draw.text((112, 518), 'Shared on OrcAgent', font=_font(dm, True, 22), fill=_WHITE)
    draw.text((112, 548), 'Open the post from the link above', font=_font(dm, False, 15), fill=_MUTED)

    draw.rounded_rectangle([830, 516, 1126, 568], radius=26, fill=_GOLD2)
    draw.text((871, 529), 'VIEW ON ORCAGENT  ->', font=_font(dm, True, 18), fill=(12, 13, 15))

    draw.line([(50, 585), (W - 50, 585)], fill=(104, 76, 37), width=1)
    draw.text((54, 597), 'OrcAgent.fun', font=_font(dm, True, 17), fill=_GOLD2)
    draw.text((510, 599), 'BIGGER MEMES. BRIGHTER TRADES.', font=_font(dm, False, 12), fill=(169, 153, 129))
    draw.text((995, 599), 'SHARE THE ALPHA', font=_font(dm, True, 12), fill=(169, 153, 129))


def install(dm):
    if getattr(dm, '_orca_concept_d_share_card_installed', False):
        return
    dm._orca_concept_d_share_card_installed = True

    def _concept_d_chart(img, symbol, price, chg24h):
        _draw_common(dm, img, symbol, float(price or 0), float(chg24h or 0), mode='CHART')

    def _concept_d_trade(img, symbol, side, entry_price, exit_price, pnl_pct, pnl_sol, pnl_currency='SOL'):
        side_text = (side or 'BUY').upper()
        price = float(exit_price or entry_price or 0)
        pnl = float(pnl_sol or 0)
        sign = '+' if pnl >= 0 else ''
        sub = f'{sign}{pnl:.4f} {pnl_currency}  ·  ENTRY {_fmt_price(entry_price)}'
        _draw_common(dm, img, symbol, price, float(pnl_pct or 0), mode=side_text, subline=sub)

    # Existing generation functions resolve these names from dashboard.py's
    # module globals at call time, so replacing the attributes here updates
    # /api/trade-card/<id>.png and X media uploads without duplicating routes.
    dm._tc_draw_chart_content = _concept_d_chart
    dm._tc_draw_content = _concept_d_trade
