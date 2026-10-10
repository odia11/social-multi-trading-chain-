"""Light mode (white with gold) for the whole app.

The app was built dark-only: about four thousand hard-coded colours across
the stylesheets and the inline <style> blocks of the templates. Rewriting
them by hand would take weeks and drift, so this module DERIVES the light
theme from the dark one:

- every stylesheet the page loads gets a companion, /theme-light/<file>.css,
  and every inline <style> block gets a companion block right after it. A
  companion only restates the colour declarations of its source, mapped to
  light, under html[data-theme="light"] -- so dark mode is untouched and the
  switch is instant (one attribute).
- the server sets data-theme="light" on <html> from the oa_theme cookie, so a
  light page is light from its first paint, with no dark flash.
- static/theme-light.js handles what only exists at runtime: inline style
  attributes and SVG colours written by JavaScript, and <style> elements
  JavaScript adds.

The mapping (map_color) keeps the brand: gold, green and red stay themselves
as fills; dark surfaces become warm white (cards white, the page a warm
off-white), light text becomes dark ink, and bright coloured TEXT is
darkened until it is readable on white. Text on a gold/green/red button keeps
its colour, since its background keeps its colour too.

theme-light.js carries a port of the same mapping; tests/test_light_mode.py
checks the two agree.
"""
from __future__ import annotations

import colorsys
import hashlib
import os
import re
import threading

ATTR = 'html[data-theme="light"]'
COOKIE = 'oa_theme'

# ── colours ─────────────────────────────────────────────────────────────────
_NAMED = {
    'white': (255, 255, 255), 'black': (0, 0, 0), 'red': (255, 0, 0),
    'green': (0, 128, 0), 'blue': (0, 0, 255), 'yellow': (255, 255, 0),
    'orange': (255, 165, 0), 'gold': (255, 215, 0), 'gray': (128, 128, 128),
    'grey': (128, 128, 128), 'silver': (192, 192, 192),
}
COLOR_RE = re.compile(
    r'#[0-9a-fA-F]{3,8}\b|rgba?\([^()]*\)|hsla?\([^()]*\)|\b(?:%s)\b' % '|'.join(_NAMED),
    re.I)


def parse_color(tok):
    t = tok.strip().lower()
    if t in _NAMED:
        r, g, b = _NAMED[t]
        return r, g, b, 1.0
    if t.startswith('#'):
        h = t[1:]
        if len(h) in (3, 4):
            h = ''.join(c * 2 for c in h)
        if len(h) not in (6, 8):
            return None
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        except ValueError:
            return None
        return r, g, b, a
    m = re.match(r'(rgba?|hsla?)\(([^()]*)\)$', t)
    if not m:
        return None
    parts = [p for p in re.split(r'[\s,/]+', m.group(2).strip()) if p]
    if len(parts) < 3 or any('var' in p or 'calc' in p for p in parts):
        return None
    try:
        def num(p, scale):
            return float(p[:-1]) * scale / 100 if p.endswith('%') else float(p)
        a = 1.0
        if len(parts) > 3:
            a = num(parts[3], 1.0)
        if m.group(1).startswith('rgb'):
            r, g, b = (num(p, 255) for p in parts[:3])
        else:
            hue = float(parts[0].replace('deg', '')) / 360.0
            s, l = num(parts[1], 1.0), num(parts[2], 1.0)
            rr, gg, bb = colorsys.hls_to_rgb(hue % 1.0, l, s)
            r, g, b = rr * 255, gg * 255, bb * 255
    except ValueError:
        return None
    clamp = lambda v: max(0.0, min(255.0, v))
    return clamp(r), clamp(g), clamp(b), max(0.0, min(1.0, a))


def _lum(r, g, b):
    def ch(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast_on_white(r, g, b):
    return 1.05 / (_lum(r, g, b) + 0.05)


def _hsl(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    return h, s, l


def _rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return r * 255, g * 255, b * 255


def _fmt(r, g, b, a):
    r, g, b = (int(round(max(0, min(255, v)))) for v in (r, g, b))
    if a >= 0.999:
        return '#%02x%02x%02x' % (r, g, b)
    return 'rgba(%d,%d,%d,%s)' % (r, g, b, ('%.3f' % a).rstrip('0').rstrip('.') or '0')


def _warm(l):
    """Light neutrals get a faint warm (gold) cast; darker ones stay ink."""
    if l > 0.8:
        return 42 / 360.0, min(0.32, 0.32 * (l - 0.8) / 0.2)
    return 220 / 360.0, 0.08


def is_vivid(rgba):
    """A real colour (gold, green, red...) rather than a grey/near-black."""
    r, g, b, _a = rgba
    h, s, l = _hsl(r, g, b)
    return s * (1 - abs(2 * l - 1)) >= 0.12


def map_rgba(rgba, role):
    """role: text | bg | border | shadow | var"""
    r, g, b, a = rgba
    if a <= 0.001:
        return rgba
    h, s, l = _hsl(r, g, b)
    if not is_vivid(rgba):
        if role == 'shadow':
            return (0, 0, 0, round(a * (0.35 if l < 0.5 else 0.15), 3))
        if role == 'bg' and l < 0.03 and a < 0.95:
            return (0, 0, 0, round(a * 0.5, 3))        # a scrim keeps dimming
        if role in ('bg', 'border') and l >= 0.98 and a >= 0.9:
            return rgba                                 # white stays white (knobs, white chips)
        if role == 'var':
            role = 'bg' if l < 0.5 else 'text'
        if role == 'text':
            if l >= 0.5:                                # body text, muted text
                nl = min(1.0 - l, 0.58)
            elif l >= 0.2:                              # dim text (placeholders, hints)
                nl = 0.62 - (0.5 - l) * 0.3
            else:                                       # dark text on a light chip
                nl = 0.96
        elif l > 0.5:                                   # a light surface (white chip)
            nl = max(0.08, 1.0 - l)
        elif role == 'border':
            nl = 1.0 - l * 0.75
        elif l <= 0.065:
            nl = 0.962                                  # the page
        elif l <= 0.14:
            nl = 1.0 - (l - 0.065) * 0.35               # cards: white
        else:
            nl = 1.0 - l * 0.75                         # inputs, hovers, pills
        wh, ws = _warm(nl)
        nr, ng, nb = _rgb(wh, ws, nl)
        return (nr, ng, nb, a)
    # a real colour
    if role == 'shadow':
        return (r, g, b, round(a * 0.6, 3))
    if role in ('bg', 'border', 'var'):
        if l < 0.22 and a > 0.5:                        # a dark tinted surface
            nl = 0.93 + (0.22 - l) * 0.2
            nr, ng, nb = _rgb(h, min(s, 0.55), nl)
            return (nr, ng, nb, a)
        # Pale gold (and other light vivid fills) deepen a little so a gold
        # button still reads as gold on a white page; translucent tints stay.
        if a >= 0.5 and l > 0.55 and _contrast_on_white(r, g, b) < 2.4:
            return _darken(h, s, l, a, 2.4, 0.8)
        return rgba
    # coloured text: readable on white, same hue
    if l < 0.22:
        nr, ng, nb = _rgb(h, s, 1.0 - l)
        return (nr, ng, nb, a)
    if _contrast_on_white(r, g, b) >= 3.0:
        return rgba
    return _darken(h, s, l, a, 3.0, 0.7)


def _darken(h, s, l, a, target, gold_sat):
    """Same hue, darker until it reads on white. Gold also loses a little
    saturation on the way down, or it turns orange-brown instead of antique gold."""
    if 25 / 360.0 <= h <= 60 / 360.0:
        s *= gold_sat
    nl = l
    cr, cg, cb = _rgb(h, s, nl)
    while _contrast_on_white(cr, cg, cb) < target and nl > 0.22:
        nl -= 0.01
        cr, cg, cb = _rgb(h, s, nl)
    return (cr, cg, cb, a)


def map_token(tok, role):
    if tok.lower() in ('transparent', 'currentcolor', 'inherit', 'initial', 'unset', 'none'):
        return tok
    rgba = parse_color(tok)
    if rgba is None:
        return tok
    return _fmt(*map_rgba(rgba, role))


# ── declarations ────────────────────────────────────────────────────────────
_TEXT_PROPS = {'color', 'fill', 'stroke', 'caret-color', 'accent-color', '-webkit-text-fill-color',
               'text-decoration-color', 'stop-color', '-webkit-text-stroke-color', 'scrollbar-color'}
_BG_PROPS = {'background', 'background-color', 'background-image'}
_SHADOW_PROPS = {'box-shadow', 'text-shadow', 'filter', '-webkit-box-shadow'}


def role_of(prop):
    p = prop.strip().lower()
    if p.startswith('--'):
        return 'var'
    if p in _TEXT_PROPS:
        return 'text'
    if p in _BG_PROPS:
        return 'bg'
    if p in _SHADOW_PROPS:
        return 'shadow'
    if p.startswith(('border', 'outline', 'column-rule')) and not re.search(
            r'radius|width|style|collapse|spacing|image|offset', p):
        return 'border'
    return None


def map_value(value, role):
    return COLOR_RE.sub(lambda m: map_token(m.group(0), role), value)


def _split_top(text, sep):
    out, depth, buf, quote = [], 0, [], None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth = max(0, depth - 1)
        elif ch == sep and depth == 0:
            out.append(''.join(buf))
            buf = []
            continue
        buf.append(ch)
    out.append(''.join(buf))
    return out


_VAR_DEF_RE = re.compile(r'(--[\w-]+)\s*:\s*([^;{}]+)')
_VAR_USE_RE = re.compile(r'var\(\s*(--[\w-]+)')


def _keeps_text(bg_value, variables):
    """A coloured or white button: its own text colour stays."""
    m = COLOR_RE.search(bg_value)
    if not m:
        v = _VAR_USE_RE.search(bg_value)
        resolved = variables.get(v.group(1)) if v else None
        m = COLOR_RE.search(resolved) if resolved else None
    c = parse_color(m.group(0)) if m else None
    if not c or c[3] < 0.6:
        return False
    _h, _s, l = _hsl(*c[:3])
    if not is_vivid(c):
        return l >= 0.98 and c[3] >= 0.9
    return 0.3 <= l <= 0.85


def map_declarations(block, variables=None):
    """The colour declarations of one rule, mapped. '' when none."""
    # Every colour PROPERTY of the rule, literal colour or not (var(--x),
    # inherit, transparent): a companion restates them all so the cascade
    # between companions is the cascade between their sources.
    decls = []
    for raw in _split_top(block, ';'):
        if ':' not in raw:
            continue
        prop, val = raw.split(':', 1)
        prop = prop.strip()
        if not prop or role_of(prop) is None:
            continue
        if prop.startswith('--') and not COLOR_RE.search(val):
            continue                                     # a non-colour custom property
        decls.append((prop, val.strip()))
    if not decls:
        return ''
    # Text on a coloured button keeps its colour: the button keeps its own.
    keep_text = any(role_of(p) == 'bg' and _keeps_text(v, variables or {}) for p, v in decls)
    # Every colour declaration is restated, changed or not: the companion
    # rules carry extra specificity, so a rule left out (gold stays gold)
    # would lose to a companion of a rule it used to beat.
    out = []
    for prop, val in decls:
        role = role_of(prop)
        if role is None:
            continue
        mapped = val if (keep_text and role == 'text') else map_value(val, role)
        out.append('%s:%s' % (prop, mapped))
    return ';'.join(out)


# ── stylesheets ─────────────────────────────────────────────────────────────
_COMMENT_RE = re.compile(r'/\*.*?\*/', re.S)
_SKIP_AT = ('@keyframes', '@-webkit-keyframes', '@font-face', '@page', '@import', '@charset',
            '@property', '@counter-style', '@view-transition')


# Elements that look the same in both themes: the OrcAgent mark (a dark
# triangle on a gold tile) keeps its dark triangle.
KEEP_SELECTOR_RE = re.compile(r'logo-(?:mark|tile|shape)|desk-logo|oa-brand-mark', re.I)


def prefix_selector(sel):
    parts = []
    for s in _split_top(sel, ','):
        s = s.strip()
        if not s:
            continue
        if s.startswith('::') or s.startswith('@'):
            return ''
        low = s.lower()
        if low.startswith(':root'):
            parts.append(ATTR + s[5:])
        elif re.match(r'html(?![\w-])', low):
            parts.append(ATTR + s[4:])
        else:
            parts.append(ATTR + ' ' + s)
    return ','.join(parts)


def _blocks(css):
    """Yield (prelude, body, is_block) at one nesting level."""
    i, n = 0, len(css)
    while i < n:
        j = css.find('{', i)
        k = css.find(';', i)
        if j < 0:
            return
        if 0 <= k < j and css[i:k].strip().startswith('@'):
            i = k + 1                                   # @import ...;
            continue
        prelude = css[i:j].strip()
        depth, p, quote = 1, j + 1, None
        while p < n and depth:
            ch = css[p]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ('"', "'"):
                quote = ch
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
            p += 1
        yield prelude, css[j + 1:p - 1]
        i = p


def light_css(css, variables=None):
    """Companion stylesheet: the colour rules of `css`, mapped, scoped to light."""
    css = _COMMENT_RE.sub('', css or '')
    if variables is None:
        variables = dict(_VAR_DEF_RE.findall(css))
    out = []
    for prelude, body in _blocks(css):
        low = prelude.lower()
        if low.startswith(_SKIP_AT):
            continue
        if low.startswith('@'):
            inner = light_css(body, variables)
            if inner:
                out.append('%s{%s}' % (prelude, inner))
            continue
        if KEEP_SELECTOR_RE.search(prelude):
            continue
        # Explicit light-theme rules already contain their intended colours.
        # Remapping them turns dark text pale and dark scrims into white veils.
        if re.search(r'\[\s*data-theme\s*=\s*[\"\x27]?light[\"\x27]?\s*\]', prelude, re.I):
            out.append('%s{%s}' % (prelude, body))
            continue
        sel = prefix_selector(prelude)
        if not sel:
            continue
        decls = map_declarations(body, variables)
        if decls:
            out.append('%s{%s}' % (sel, decls))
    return '\n'.join(out)


_cache_lock = threading.Lock()
_inline_cache = {}
_file_cache = {}


def light_css_cached(css):
    key = hashlib.sha1(css.encode('utf-8', 'replace'), usedforsecurity=False).hexdigest()
    with _cache_lock:
        hit = _inline_cache.get(key)
    if hit is not None:
        return hit
    out = light_css(css)
    with _cache_lock:
        if len(_inline_cache) > 600:
            _inline_cache.clear()
        _inline_cache[key] = out
    return out


# ── pages ───────────────────────────────────────────────────────────────────
_STYLE_BLOCK_RE = re.compile(r'(<style\b(?![^>]*data-oa-l)[^>]*>)(.*?)(</style>)', re.S | re.I)
_LINK_RE = re.compile(r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*>', re.I)
_HREF_RE = re.compile(r'\bhref=["\'](/static/([\w./-]+?\.css))(?:\?[^"\']*)?["\']', re.I)
_MEDIA_RE = re.compile(r'\bmedia=["\']([^"\']*)["\']', re.I)
_HTML_TAG_RE = re.compile(r'<html\b([^>]*)>', re.I)


def transform_html(html, light, version='1'):
    """The theme on <html>, the runtime in <head>, and -- for a light page --
    companions for every stylesheet and <style> block. A dark page carries no
    companions at all (nothing extra to download); switching to light builds
    them in the browser (theme-light.js) from the same rules."""
    if light:
        html = _companions(html, version)
    m = _HTML_TAG_RE.search(html)
    if m and 'data-theme=' not in m.group(1):
        theme = ' data-theme="light"' if light else ''
        html = html[:m.start()] + '<html%s%s>' % (m.group(1), theme) + html[m.end():]
    head = html.find('<head')
    if head >= 0 and 'theme-light.js' not in html:
        end = html.find('>', head) + 1
        boot = ('<meta name="oa-theme" content="%s">'
                '<link rel="stylesheet" href="/static/theme-light-base.css?v=%s" data-oa-light="1">'
                '<script src="/static/theme-light.js?v=%s"></script>'
                % ('light' if light else 'dark', version, version))
        html = html[:end] + boot + html[end:]
    return html


def _companions(html, version):
    def style_block(m):
        open_tag, body, close = m.group(1), m.group(2), m.group(3)
        tag = open_tag[:-1] + ' data-oa-lt="1">'
        extra = light_css_cached(body)
        if not extra:
            return tag + body + close
        return tag + body + close + '<style data-oa-light="1">' + extra + '</style>'
    html = _STYLE_BLOCK_RE.sub(style_block, html)

    present = set(re.findall(r'data-oa-light-for="([^"]+)"', html))

    def link(m):
        tag = m.group(0)
        if 'data-oa-light' in tag:
            return tag
        h = _HREF_RE.search(tag)
        if not h or h.group(2).startswith('theme-light') or h.group(2) in present:
            return tag
        present.add(h.group(2))
        media = _MEDIA_RE.search(tag)
        media_attr = ''
        if media and media.group(1) not in ('all', 'print'):
            media_attr = ' media="%s"' % media.group(1)
        return (tag + '<link rel="stylesheet" href="/theme-light/%s?v=%s" data-oa-light-for="%s"%s>'
                % (h.group(2), version, h.group(2), media_attr))
    return _LINK_RE.sub(link, html)


def install(d):
    app = d.app
    if getattr(app, '_orca_theme_light', False):
        return
    app._orca_theme_light = True
    from flask import Response, abort, request
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

    @app.route('/theme-light/<path:name>')
    def theme_light_css(name):
        if not re.fullmatch(r'[\w-]+(?:/[\w-]+)*\.css', name) or '..' in name:
            abort(404)
        path = os.path.join(static_dir, name)
        if not os.path.isfile(path):
            abort(404)
        mtime = os.path.getmtime(path)
        with _cache_lock:
            hit = _file_cache.get(name)
        if not hit or hit[0] != mtime:
            with open(path, encoding='utf-8', errors='replace') as f:
                hit = (mtime, light_css(f.read()))
            with _cache_lock:
                _file_cache[name] = hit
        resp = Response(hit[1], mimetype='text/css')
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if request.args.get('v') \
            else 'public, max-age=300'
        return resp

    @app.after_request
    def _theme_light_pages(response):
        try:
            if response.status_code != 200 or response.direct_passthrough:
                return response
            if 'text/html' not in (response.content_type or '').lower():
                return response
            html = response.get_data(as_text=True)
            if '<head' not in html:
                return response
            light = request.cookies.get(COOKIE) == 'light'
            version = str(getattr(d, '_APP_VERSION', '1'))
            response.set_data(transform_html(html, light, version))
            response.headers['Vary'] = ', '.join(filter(None, [response.headers.get('Vary'), 'Cookie']))
        except Exception as exc:                        # never break a page over its colours
            try:
                app.logger.warning('light theme skipped: %s', exc)
            except Exception:
                pass
        return response
