"""Render static/og-orcagent.png -- the 1200x630 link preview X, Telegram,
Discord, WhatsApp, etc. show when someone shares https://orcagent.fun.

    python3 tools/make_og_image.py

Uses the bundled Geist / JetBrains Mono fonts (fonts/, OFL), so the output is
the same on any machine.
"""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
FONTS = os.path.join(ROOT, 'fonts')
OUT = os.path.join(ROOT, 'static', 'og-orcagent.png')
W, H = 1200, 630
S = 2                                   # draw at 2x, downsample for smooth edges

BG = (8, 11, 16)
GOLD = (247, 185, 85)
GOLD2 = (255, 211, 106)
WHITE = (243, 245, 248)
SUB = (154, 163, 176)
MUTED = (111, 120, 134)
LINE = (35, 43, 53)
CARD = (16, 21, 28)
GREEN = (53, 214, 162)
RED = (255, 93, 112)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size * S)


def s(v):
    return int(round(v * S))


def main():
    img = Image.new('RGB', (W * S, H * S), BG)

    # Soft gold glow top-right and a fainter one bottom-left.
    glow = Image.new('RGB', img.size, BG)
    g = ImageDraw.Draw(glow)
    g.ellipse([s(760), s(-260), s(1420), s(360)], fill=(58, 44, 20))
    g.ellipse([s(-300), s(420), s(300), s(900)], fill=(22, 26, 32))
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(s(90))), 1.0)
    d = ImageDraw.Draw(img)

    # Faint grid: a light overlay, so it reads the same over the glow.
    grid = Image.new('RGBA', img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 60):
        gd.line([s(x), 0, s(x), s(H)], fill=(255, 255, 255, 7), width=S)
    for y in range(0, H, 60):
        gd.line([0, s(y), s(W), s(y)], fill=(255, 255, 255, 7), width=S)
    img.paste(grid, (0, 0), grid)
    d = ImageDraw.Draw(img)

    # Brand: gold tile with the black triangle + wordmark.
    x0, y0 = 72, 52
    d.rounded_rectangle([s(x0), s(y0), s(x0 + 64), s(y0 + 64)], radius=s(18), fill=GOLD)
    cx, cy = x0 + 32, y0 + 34
    d.polygon([(s(cx), s(cy - 15)), (s(cx - 15), s(cy + 11)), (s(cx + 15), s(cy + 11))], fill=BG)
    d.text((s(x0 + 84), s(y0 + 30)), 'OrcAgent', font=font('Geist-ExtraBold.ttf', 40), fill=WHITE, anchor='lm')

    # Headline.
    hf = font('Geist-ExtraBold.ttf', 84)
    d.text((s(72), s(226)), 'Trade it.', font=hf, fill=WHITE, anchor='ls')
    d.text((s(72), s(316)), 'Share it.', font=hf, fill=GOLD, anchor='ls')

    # Subline.
    sf = font('Geist-Medium.ttf', 28)
    for i, line in enumerate(('Multi-chain social trading.', 'Discover tokens, follow traders,', 'trade across chains with USDC.')):
        d.text((s(72), s(370 + i * 38)), line, font=sf, fill=SUB, anchor='ls')

    # Chains.
    cf = font('JetBrainsMono-Bold.ttf', 17)
    x = 72
    for name in ('Solana', 'Base', 'BNB', 'Arbitrum', 'Polygon', 'Robinhood'):
        tw = d.textlength(name, font=cf) / S
        d.rounded_rectangle([s(x), s(478), s(x + tw + 28), s(512)], radius=s(17), outline=LINE, width=s(1.5), fill=(12, 16, 22))
        d.text((s(x + 14 + tw / 2), s(495)), name, font=cf, fill=(201, 207, 216), anchor='mm')
        x += tw + 38

    # Site.
    d.text((s(72), s(572)), 'orcagent.fun', font=font('JetBrainsMono-ExtraBold.ttf', 24), fill=GOLD, anchor='ls')

    # Right: a token card, the thing people share.
    L, T, R, B = 760, 118, 1128, 520
    shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([s(L), s(T + 16), s(R), s(B + 16)], radius=s(28), fill=(0, 0, 0, 170))
    img.paste(shadow.filter(ImageFilter.GaussianBlur(s(22))), (0, 0), shadow.filter(ImageFilter.GaussianBlur(s(22))))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([s(L), s(T), s(R), s(B)], radius=s(28), fill=CARD, outline=(44, 53, 66), width=s(1.5))

    # Tag + token row.
    tf = font('Geist-ExtraBold.ttf', 14)
    d.rounded_rectangle([s(L + 26), s(T + 26), s(L + 150), s(T + 54)], radius=s(14), fill=(52, 40, 20))
    d.text((s(L + 88), s(T + 40)), 'TRENDING', font=tf, fill=GOLD, anchor='mm')
    d.ellipse([s(L + 26), s(T + 74), s(L + 82), s(T + 130)], fill=(28, 34, 44), outline=GOLD, width=s(2))
    d.text((s(L + 54), s(T + 102)), 'W', font=font('Geist-ExtraBold.ttf', 24), fill=GOLD, anchor='mm')
    d.text((s(L + 98), s(T + 94)), '$WOJAK', font=font('Geist-ExtraBold.ttf', 30), fill=WHITE, anchor='ls')
    d.text((s(L + 98), s(T + 122)), 'Solana · Raydium', font=font('Geist-Medium.ttf', 16), fill=MUTED, anchor='ls')
    d.text((s(R - 26), s(T + 41)), '$0.00184', font=font('JetBrainsMono-ExtraBold.ttf', 22), fill=WHITE, anchor='rm')
    d.rounded_rectangle([s(R - 132), s(T + 76), s(R - 26), s(T + 106)], radius=s(8), fill=(18, 52, 43))
    d.text((s(R - 79), s(T + 91)), '+184.2%', font=font('JetBrainsMono-ExtraBold.ttf', 16), fill=GREEN, anchor='mm')

    # Sparkline with a soft fill.
    pts = [0.62, 0.66, 0.58, 0.6, 0.5, 0.54, 0.44, 0.47, 0.36, 0.4, 0.3, 0.24, 0.28, 0.16, 0.1]
    cl, cr, ct, cb = L + 26, R - 26, T + 158, T + 268
    coords = [(s(cl + (cr - cl) * i / (len(pts) - 1)), s(ct + (cb - ct) * p)) for i, p in enumerate(pts)]
    fill = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(fill).polygon(coords + [(s(cr), s(cb)), (s(cl), s(cb))], fill=(53, 214, 162, 38))
    img.paste(fill, (0, 0), fill)
    d = ImageDraw.Draw(img)
    d.line(coords, fill=GREEN, width=s(3.5), joint='curve')
    lx, ly = coords[-1]
    d.ellipse([lx - s(6), ly - s(6), lx + s(6), ly + s(6)], fill=GREEN)

    # Buyers vs sellers.
    lf = font('JetBrainsMono-Bold.ttf', 13)
    d.text((s(cl), s(T + 300)), 'BUYS 1,204', font=lf, fill=GREEN, anchor='ls')
    d.text((s(cr), s(T + 300)), '38 SELLS', font=lf, fill=RED, anchor='rs')
    d.rounded_rectangle([s(cl), s(T + 310), s(cr), s(T + 320)], radius=s(5), fill=RED)
    d.rounded_rectangle([s(cl), s(T + 310), s(cl + (cr - cl) * 0.93), s(T + 320)], radius=s(5), fill=GREEN)

    # Trade button.
    d.rounded_rectangle([s(cl), s(T + 340), s(cr), s(T + 382)], radius=s(12), fill=GOLD2)
    d.text((s((cl + cr) / 2), s(T + 361)), 'Trade  $WOJAK', font=font('Geist-ExtraBold.ttf', 18), fill=(17, 19, 24), anchor='mm')

    img = img.resize((W, H), Image.LANCZOS)
    img.save(OUT, 'PNG', optimize=True)
    print(OUT, os.path.getsize(OUT), 'bytes')


if __name__ == '__main__':
    main()
