Warning: truncated output (original token count: 381797)
... 478609 bytes omitted ...

import threading, time, json, os, sys, subprocess, requests, logging, datetime, sqlite3, re, functools, struct, base64, math, hashlib, hmac, secrets, binascii, shutil, uuid, html as _html_lib, traceback, random
import io
import socket
import ipaddress
import urllib.parse
import calendar
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from PIL import Image, ImageDraw, ImageFont
import bcrypt as _bcrypt
try:
    import nacl.public as _nacl_public
    import nacl.signing as _nacl_signing
    _NACL_OK = True
except ImportError:
    _NACL_OK = False
    _nacl_signing = None
try:
    import webauthn as _webauthn
    from webauthn.helpers.structs import (
        AuthenticatorSelectionCriteria as _WaAuthenticatorSelectionCriteria,
        UserVerificationRequirement as _WaUserVerificationRequirement,
        ResidentKeyRequirement as _WaResidentKeyRequirement,
        AttestationConveyancePreference as _WaAttestationConveyancePreference,
        PublicKeyCredentialDescriptor as _WaPublicKeyCredentialDescriptor,
    )
    from webauthn.helpers.exceptions import InvalidRegistrationResponse as _WaInvalidRegistrationResponse, \
        InvalidAuthenticationResponse as _WaInvalidAuthenticationResponse
    _WEBAUTHN_OK = True
except ImportError:
    _WEBAUTHN_OK = False
    _webauthn = None
try:
    from apscheduler.schedulers.background import BackgroundScheduler as _BgScheduler
    from apscheduler.triggers.cron import CronTrigger as _CronTrigger
    _APSCHEDULER_OK = True
except ImportError:
    _APSCHEDULER_OK = False
try:
    from flask_compress import Compress as _Compress
    _COMPRESS_OK = True
except ImportError:
    _COMPRESS_OK = False
from contextlib import contextmanager
from flask import Flask, jsonify, request, session, render_template, redirect, make_response, send_from_directory
from markupsafe import Markup
import gzip
import shutil
import traceback
from decimal import Decimal, ROUND_UP
from werkzeug.exceptions import HTTPException
# Pure arithmetic, no external dependencies -- see trade_engine/costs.py.
# Imported unguarded on purpose: a silent fallback here would let the app
# start with the spend ceiling missing, which is the one failure this
# module exists to prevent. tests/test_module_imports.py catches breakage.
from trade_engine import registry as te_registry
from trade_engine import ledger as te_ledger
from trade_engine import subsidy as te_subsidy
from trade_engine import execute as te_execute
from trade_engine.costs import CostError as TeCostError
from trade_engine.providers import JupiterProvider, ZeroExProvider, ProviderError as TeProviderError
from trade_engine.quote import QuoteError as TeQuoteError, QuoteRequest, build_quote
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv
from eth_account import Account as _EvmAccount  # BSC (EVM) keypair generation --
                                                  # aliased to avoid clashing with any
                                                  # local variable named "Account"
try:
    from pywebpush import webpush, WebPushException
    _PYWEBPUSH_OK = True
except ImportError:
    _PYWEBPUSH_OK = False

def _safe_external_image_url(url: str) -> bool:
    """True if url is safe for the SERVER to fetch on a caller's behalf --
    http(s) only, and every address the hostname resolves to is a public,
    non-reserved IP (blocks loopback/private/link-local/cloud-metadata/
    multicast/reserved ranges). Checks every resolved address, not just the
    first, since a DNS name can resolve to several.

    banner_url in _tc_build_canvas() below comes from DexScreener's
    per-token "info.header" field, which is attacker-settable for any
    token they mint -- not a value this server controls or can otherwise
    trust, so this check runs before ever fetching it (found by this
    session's security audit: without it, minting a token whose
    DexScreener profile points 'header' at e.g. 169.254.169.254 or an
    internal service, then referencing that mint from a feed post's
    __TRADE__/__CHART__ embed, made /api/trade-card/<id>.png fetch
    whatever internal URL the attacker chose)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ('http', 'https'):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local or
                ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True

_TC_FONT_CACHE = {}
def _tc_font(bold, size):
    """Loads the same JetBrains Mono the app's own UI uses (vendored at
    static/fonts/ -- see that dir's font files) so the shareable trade/chart
    card image actually looks like the in-app trade card
    (_renderTradeTerminalCard() in dashboard.js) instead of PIL's generic
    bitmap default font. Falls back to that default only if the TTF is ever
    missing, so a card still renders (just visually mismatched) rather than
    erroring out. Cached per (bold, size) -- this runs on every share/unfurl
    request, not once at startup."""
    key = (bold, size)
    cached = _TC_FONT_CACHE.get(key)
    if cached:
        return cached
    path = os.path.join(BASE, 'static', 'fonts', 'JetBrainsMono-Bold.ttf' if bold else 'JetBrainsMono-Regular.ttf')
    try:
        font = ImageFont.truetype(path, size)
    except Exception:
        font = ImageFont.load_default(size=size)
    _TC_FONT_CACHE[key] = font
    return font

def _tc_build_canvas(banner_url=None):
    """Build the base 1200x630 canvas for a server-rendered trade card image.
    Falls back to a flat background if banner_url is missing, fails the
    _safe_external_image_url() SSRF check, or fails to load."""
    W, H = 1200, 630
    canvas = Image.new('RGB', (W, H), '#0d1117')
    if banner_url and _safe_external_image_url(banner_url):
        try:
            resp = requests.get(banner_url, timeout=5)
            resp.raise_for_status()
            banner = Image.open(io.BytesIO(resp.content)).convert('RGB')
            src_w, src_h = banner.size
            # "Contain", not "cover": scale to fit entirely inside the canvas
            # and letterbox with the dark background rather than cropping to
            # fill it. Token banners are often much wider than 1200x630 (a
            # mascot on one side, a logo/title on the other) -- covering
            # cropped whichever side landed outside the frame, cutting off
            # part of the banner's own text/logo entirely.
            scale = min(W / src_w, H / src_h)
            new_w, new_h = round(src_w * scale), round(src_h * scale)
            banner = banner.resize((new_w, new_h), Image.LANCZOS)
            left, top = (W - new_w) // 2, (H - new_h) // 2
            canvas.paste(banner, (left, top))
        except Exception:
            pass
    return canvas

def _tc_draw_content(img, symbol, side, entry_price, exit_price, pnl_pct, pnl_sol, pnl_currency='SOL'):
    """Draw the trade-card overlay (gradient, badge, symbol/prices, PNL) in-place
    onto img (as produced by _tc_build_canvas). Returns nothing."""
    W, H = img.size
    entry_price = float(entry_price or 0)
    exit_price  = float(exit_price or 0)
    pnl_pct     = float(pnl_pct or 0)
    pnl_sol     = float(pnl_sol or 0)
    is_buy      = (side or 'BUY').upper() != 'SELL'
    side_col    = (0, 208, 132) if is_buy else (255, 71, 87)     # #00d084 / #ff4757
    pct_col     = (0, 208, 132) if pnl_pct >= 0 else (255, 71, 87)

    # Same gradient as the in-app trade card's own CSS -- this image is
    # meant to be the same design as _renderTradeTerminalCard() in
    # dashboard.js (the card already shown inside the app), not a separate
    # invented one: linear-gradient(to bottom, rgba(13,17,23,.55),
    # rgba(13,17,23,.92)), i.e. alpha 140 at the top fading to 235 at the
    # bottom -- no boxed badge, no solid panels behind the text.
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for y in range(H):
        alpha = int(140 + (235 - 140) * (y / H))
        odraw.line([(0, y), (W, y)], fill=(13, 17, 23, alpha))
    img.paste(overlay, (0, 0), overlay)

    draw = ImageDraw.Draw(img)

    def _fmt_price(p):
        if not p:
            return '—'
        return f'${p:.8f}'.rstrip('0').rstrip('.') if p < 0.001 else f'${p:.6f}'

    badge_font = _tc_font(True, 28)
    sym_font   = _tc_font(True, 46)
    price_font = _tc_font(False, 30)
    sol_font   = _tc_font(True, 32)
    pct_font   = _tc_font(True, 90)

    # SELL/BUY and $SYMBOL sit on one line, like the in-app card's <span>s --
    # the badge is plain colored text (the CSS border on it is 20% opacity,
    # practically invisible), not a filled/outlined box.
    bx, by = 40, 40
    badge_text = 'BUY' if is_buy else 'SELL'
    tb = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w, badge_h = tb[2] - tb[0], tb[3] - tb[1]
    sym_text = '$' + symbol
    tbs = draw.textbbox((0, 0), sym_text, font=sym_font)
    sym_h = tbs[3] - tbs[1]
    line_y = by + max(badge_h, sym_h)
    draw.text((bx, line_y - badge_h), badge_text, font=badge_font, fill=side_col)
    sym_x = bx + badge_w + 20
    draw.text((sym_x, line_y - sym_h), sym_text, font=sym_font, fill=(238, 241, 245))

    price_y = by + max(badge_h, sym_h) + 22
    # '->' not '→' -- the vendored JetBrainsMono subset (and PIL's own default
    # font) has no glyph for the arrow, which rendered as a tofu box.
    price_str = f'{_fmt_price(entry_price)} -> {_fmt_price(exit_price)}'
    draw.text((bx, price_y), price_str, font=price_font, fill=(138, 145, 156))

    sol_y = price_y + 42
    sol_sign = '+' if pnl_sol >= 0 else ''
    # pnl_currency is whatever this trade was actually denominated in --
    # SOL only for a plain SOL-mode Solana trade, USDC/USDG for everything
    # else (an EVM chain's own stablecoin, or a USDC-mode Solana trade).
    # See _trade_currency_symbol()'s own comment for the full reasoning.
    sol_str  = f'{sol_sign}{pnl_sol:.4f} {pnl_currency}'
    draw.text((bx, sol_y), sol_str, font=sol_font, fill=(247, 185, 85))

    # PNL percentage, right-aligned, vertically centered against the text
    # block above it -- same as the in-app card's align-self:center on that
    # row, rather than centered on the whole 1200x630 canvas.
    pct_sign = '+' if pnl_pct >= 0 else ''
    pct_text = f'{pct_sign}{pnl_pct:.2f}%'
    tb2 = draw.textbbox((0, 0), pct_text, font=pct_font)
    ptw, pth = tb2[2] - tb2[0], tb2[3] - tb2[1]
    block_bottom = sol_y + 36
    pct_y = (by + block_bottom) // 2 - pth // 2
    draw.text((W - 60 - ptw, pct_y), pct_text, font=pct_font, fill=pct_col)

def _tc_draw_chart_content(img, symbol, price, chg24h):
    """Draw the chart-card overlay for a __CHART__ embed snapshot -- same canvas as
    _tc_draw_content, but there's no trade here (no entry/exit/pnl_sol), just a
    symbol, its current price, and the 24h move."""
    W, H = img.size
    price   = float(price or 0)
    chg24h  = float(chg24h or 0)
    chg_col = (0, 208, 132) if chg24h >= 0 else (255, 71, 87)

    # Same gradient formula as _tc_draw_content() -- see its comment. No
    # boxed badge, no solid panels; this should look like one consistent
    # design with the trade card, not a separately-invented style.
    overlay = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    for y in range(H):
        alpha = int(140 + (235 - 140) * (y / H))
        odraw.line([(0, y), (W, y)], fill=(13, 17, 23, alpha))
    img.paste(overlay, (0, 0), overlay)

    draw = ImageDraw.Draw(img)

    def _fmt_price(p):
        if not p:
            return '—'
        return f'${p:.8f}'.rstrip('0').rstrip('.') if p < 0.001 else f'${p:.6f}'

    badge_font = _tc_font(True, 28)
    sym_font   = _tc_font(True, 46)
    price_font = _tc_font(False, 32)
    pct_font   = _tc_font(True, 90)

    bx, by = 40, 40
    badge_text = 'CHART'
    tb = draw.textbbox((0, 0), badge_text, font=badge_font)
    badge_w, badge_h = tb[2] - tb[0], tb[3] - tb[1]
    sym_text = '$' + symbol
    tbs = draw.textbbox((0, 0), sym_text, font=sym_font)
    sym_h = tbs[3] - tbs[1]
    line_y = by + max(badge_h, sym_h)
    draw.text((bx, line_y - badge_h), badge_text, font=badge_font, fill=(247, 185, 85))
    sym_x = bx + badge_w + 20
    draw.text((sym_x, line_y - sym_h), sym_text, font=sym_font, fill=(238, 241, 245))

    price_y = by + max(badge_h, sym_h) + 22
    price_str = _fmt_price(price)
    draw.text((bx, price_y), price_str, font=price_font, fill=(138, 145, 156))

    pct_sign = '+' if chg24h >= 0 else ''
    pct_text = f'{pct_sign}{chg24h:.2f}%'
    tb2 = draw.textbbox((0, 0), pct_text, font=pct_font)
    ptw, pth = tb2[2] - tb2[0], tb2[3] - tb2[1]
    block_bottom = price_y + 32
    pct_y = (by + block_bottom) // 2 - pth // 2
    draw.text((W - 60 - ptw, pct_y), pct_text, font=pct_font, fill=chg_col)

def _generate_trade_card_image(symbol, side, entry_price, exit_price, pnl_pct, pnl_sol, banner_url=None, pnl_currency='SOL'):
    img = _tc_build_canvas(banner_url)
    _tc_draw_content(img, symbol, side, entry_price, exit_price, pnl_pct, pnl_sol, pnl_currency)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()

load_dotenv()

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000
if _COMPRESS_OK:
    app.config['COMPRESS_MIMETYPES'] = ['text/html','text/css','text/xml','text/javascript','application/json','application/javascript']
    _Compress(app)
def _load_secret_key(data_dir: str) -> bytes:
    """The key that signs login sessions. It has to survive a deploy.

    It did not. The generated key was written next to dashboard.py -- inside
    $APP_DIR -- and install.sh syncs that directory with `rsync --delete`
    from a clone where .secret_key is gitignored and therefore absent. So
    every single deploy deleted it, the next start generated a new one, and
    every signed session in every browser became invalid at once. Everyone
    was logged out and had to reconnect their wallet, every time, and nothing
    anywhere said why.

    Two changes, and both are needed. The key now lives in DATA_DIR, the one
    directory a redeploy does not touch, and install.sh excludes it as a
    belt-and-braces measure for any install that still has one in the old
    place. That exclusion is also what makes the migration below possible:
    without it the old key is deleted before this code ever runs, and moving
    to the new location would itself log everyone out one final time.

    SECRET_KEY in the environment still wins over all of it -- that is the
    right way to run this, because it survives losing the disk as well.
    """
    _env = os.getenv('SECRET_KEY')
    if _env:
        return _env.encode() if isinstance(_env, str) else _env

    _key_path = os.path.join(data_dir, '.secret_key')
    _legacy   = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.secret_key')

    try:
        with open(_key_path, 'rb') as _f:
            return _f.read()
    except FileNotFoundError:
        pass

    # An existing key in the old location is MOVED, not regenerated. Its whole
    # value is that it is the same key as yesterday.
    try:
        with open(_legacy, 'rb') as _f:
            _key = _f.read()
        if _key:
            with open(_key_path, 'wb') as _f:
                _f.write(_key)
            os.chmod(_key_path, 0o600)
            try:
                os.remove(_legacy)
            except OSError:
                pass
            print(f'[startup] moved the session key out of the app directory into '
                  f'{data_dir} — deploys no longer log everyone out', flush=True)
            return _key
    except FileNotFoundError:
        pass
    except Exception as _e:
        print(f'[startup] could not migrate the old session key ({_e}) — '
              f'a new one will be generated and everyone will be logged out once',
              flush=True)

    _key = os.urandom(32)
    try:
        with open(_key_path, 'wb') as _f:
            _f.write(_key)
        os.chmod(_key_path, 0o600)
        print(f'[startup] generated a new session key in {data_dir}. Everyone is '
              f'logged out once; this should not happen again.', flush=True)
    except Exception as _e:
        # A key that cannot be stored is a key that changes on every restart.
        # Say so loudly rather than looking like it worked.
        print(f'[startup] ⚠ COULD NOT SAVE the session key to {data_dir} ({_e}). '
              f'Every restart will log all users out until this is fixed — set '
              f'SECRET_KEY in /etc/orcagent.env to stop it.', flush=True)
    return _key

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_HTTPONLY']    = True
app.config['SESSION_COOKIE_SAMESITE']   = 'Lax'
# ── WHICH ENVIRONMENT THIS IS ──────────────────────────────────────────────
# These three settings -- a Secure cookie, a cookie shared between www and the
# bare domain, and HSTS -- used to be gated on RAILWAY_ENVIRONMENT. That
# variable only exists on Railway, so the day this moved to another host all
# three silently switched themselves off: the session cookie stopped being
# marked Secure, www and the bare domain stopped sharing a login, and the
# HSTS header disappeared. Nothing errored; it just quietly got less safe.
#
# So the question is now "is this production", not "is this Railway", and the
# default is YES. Getting it wrong in this direction means Secure cookies on
# a local http:// server, which is an annoyance; getting it wrong the other
# way is a security hole that nobody notices. Local development sets DEV=1.
IS_PRODUCTION = os.getenv('DEV', '').strip().lower() not in ('1', 'true', 'yes', 'on')
# The site's own domain, without a leading dot. Overridable so the domain is
# not baked into the code any more than the host was.
PUBLIC_HOST   = os.getenv('PUBLIC_HOST', 'orcagent.fun').strip().lower().lstrip('.')

app.config['SESSION_COOKIE_SECURE']     = IS_PRODUCTION
app.config['SESSION_COOKIE_PATH']       = '/'
# 'orca_s' avoids conflicts with the old 'session' cookie (no domain attr).
# The dot prefix lets both www and the bare domain share one session -- without
# it a user is logged out simply by moving between them.
if IS_PRODUCTION and PUBLIC_HOST:
    app.config['SESSION_COOKIE_NAME']   = 'orca_s'
    app.config['SESSION_COOKIE_DOMAIN'] = '.' + PUBLIC_HOST
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

@app.template_filter('fmtk')
def _jinja_fmtk(v):
    """Format a large number as 1.2K / 3.4M for use in Jinja2 templates."""
    v = float(v or 0)
    if v >= 1_000_000:
        return f'{v / 1_000_000:.1f}M'
    if v >= 1_000:
        return f'{v / 1_000:.1f}K'
    return f'{v:.0f}'

@app.template_filter('fmtprice')
def _jinja_fmtprice(v):
    """Format a token price like the client-side priceFmt() helper: more
    decimals for sub-cent prices so tiny memecoin prices stay readable.
    Uses fixed-point (not '%g') below 1 cent -- '%g' switches to scientific
    notation there (e.g. "1.23e-05"), which JS's toPrecision(3) never does
    for prices in this range."""
    v = float(v or 0)
    if v >= 1:
        return f'${v:.4f}'
    if v >= 0.01:
        return f'${v:.6f}'
    if v <= 0:
        return '$0'
    exponent = math.floor(math.log10(v))
    decimals = max(0, 2 - exponent)
    return f'${v:.{decimals}f}'

@app.before_request
def _security_gate():
    """Runs before every other before_request hook (registration order).
    IP-based blocking/banning has been removed — this only logs scanner/exploit
    probe paths for visibility, and applies a soft global rate limit (429,
    never a ban) to blunt DDoS-style floods without locking out real users."""
    ip = request.remote_addr or '0.0.0.0'
    if _BLOCKED_PROBE_RE.search(request.path):
        _log_security_event('honeypot_hit', 'anonymous', f'{request.method} {request.path} from {ip}')
    if request.query_string and _SUSPICIOUS_INPUT_RE.search(request.query_string.decode('utf-8', 'ignore')):
        _log_security_event('suspicious_input', session.get('wallet', 'anonymous'),
                            f'querystring on {request.path} from {ip}')
    if request.method in ('POST', 'PUT', 'PATCH') and (request.content_type or '').startswith('application/json'):
        body = request.get_data(as_text=True) or ''
        if body and _SUSPICIOUS_INPUT_RE.search(body):
            _log_security_event('suspicious_input', session.get('wallet', 'anonymous'),
                                f'request body on {request.path} from {ip}')
    ua = (request.headers.get('User-Agent') or '').strip()
    if ip not in _OWNER_IPS and (
        not ua or _BOT_UA_RE.search(ua)
    ):
        if request.path in _BOT_BLOCKED_PATHS:
            _log_security_event('bot_blocked', session.get('wallet', 'anonymous'),
                                f'{request.method} {request.path} ua={ua!r:.120} from {ip}')
            return jsonify({'error': 'Forbidden'}), 403
        _log_security_event('bot_probe', session.get('wallet', 'anonymous'),
                            f'{request.method} {request.path} ua={ua!r:.120} from {ip}')
    if (ip not in _OWNER_IPS and not _is_owner(session.get('wallet', ''))
            and not _rate_ok('global:' + ip, 500, 60)):
        return jsonify({'error': 'Too many requests'}), 429
    _ext_hit('api')
    return None

@app.before_request
def _refresh_session():
    if session.get('wallet'):
        session.modified = True  # extend cookie lifetime on every API call

# /api/wallet/set is the auth-bootstrap endpoint — it establishes the session so it
# cannot require a session-scoped CSRF token. Origin check still protects it.
_CSRF_EXEMPT_PATHS = frozenset({'/api/wallet/set', '/api/wallet/connect-readonly', '/api/login_password', '/api/connect-wallet', '/api/instant-trade', '/api/phantom/init', '/api/phantom/decrypt'})

def csrf_exempt(f):
    """Decorator: mark a view function as exempt from CSRF token validation.
    Origin and client-secret checks in _csrf_check() still apply.
    Use on API routes whose callers cannot forward the session CSRF token."""
    f._csrf_exempt = True
    return f

def _time_ago_str(ts_str: str) -> str:
    """'Xm'/'Xh'/'Xd' relative-time label, matching the x.com-style format
    used client-side (see _tvTimeAgo() in dashboard.js) — this is the
    server-rendered equivalent for pages like profile.html that aren't
    fetched via JS/fetch."""
    if not ts_str:
        return ''
    try:
        ts = datetime.datetime.strptime(ts_str[:19], '%Y-%m-%d %H:%M:%S')
        diff = (datetime.datetime.utcnow() - ts).total_seconds()
        if diff < 60:
            return 'now'
        if diff < 3600:
            return f'{int(diff // 60)}m'
        if diff < 86400:
            return f'{int(diff // 3600)}h'
        return f'{int(diff // 86400)}d'
    except (ValueError, TypeError):
        return ''

def _get_csrf_token() -> str:
    """Return (creating if absent) a per-session CSRF token stored in the Flask session."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_hex(32)
    return session['csrf_token']

def _validate_csrf(token: str) -> bool:
    """Constant-time CSRF token comparison — prevents timing oracle attacks."""
    expected = session.get('csrf_token', '')
    if not expected or not token:
        return False
    return hmac.compare_digest(token.encode(), expected.encode())

@app.before_request
def _csrf_check():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE') or not request.path.startswith('/api/'):
        return None
    # ── 1. Origin / Host validation — runs even for the fully-exempt paths below.
    # SECURITY FIX (see commit): this used to run AFTER the exempt-path shortcut,
    # so /api/wallet/set and friends got no Origin check at all -- not actively
    # exploitable today (they all require Content-Type: application/json,
    # forcing a CORS preflight, and none send permissive CORS headers), but
    # fragile defense-in-depth that shouldn't rely on that staying true. ──────
    origin = request.headers.get('Origin', '')
    if origin:
        host = request.headers.get('Host', '') or ''
        # Strip www. from both sides before comparing so that a browser on
        # www.orcagent.fun posting to orcagent.fun (after redirect) still passes.
        host_bare   = host.split(':')[0].removeprefix('www.')
        origin_bare = origin.split('//')[-1].split(':')[0].removeprefix('www.')
        if origin_bare not in ('localhost', '127.0.0.1') and origin_bare != host_bare:
            return jsonify({'error': 'CSRF check failed'}), 403
    # Fully exempt paths skip the client-secret + token checks below (they either
    # bootstrap auth with no session yet, or handle their own auth/CORS --
    # instant-trade has its own CORS after_request + session wallet check) --
    # but never skip the Origin check above, which always applies.
    if request.path in _CSRF_EXEMPT_PATHS:
        return None
    # ── 0. Shared client secret (only enforced if API_SHARED_SECRET is configured) ──
    if API_SHARED_SECRET:
        sent = request.headers.get('X-API-Shared-Secret', '')
        if not sent or not hmac.compare_digest(sent.encode(), API_SHARED_SECRET.encode()):
            _log_security_event('client_secret_fail', session.get('wallet', 'unknown'),
                                f'bad/missing X-API-Shared-Secret on {request.path}')
            return jsonify({'error': 'Forbidden'}), 403
    # Function-level exemption via @csrf_exempt decorator -- skips only the
    # CSRF-token check below; the origin/client-secret checks above still apply.
    _ep = app.view_functions.get(request.endpoint)
    if _ep and getattr(_ep, '_csrf_exempt', False):
        return None
    # ── 2. CSRF token for authenticated sessions ──────────────────────────────
    if session.get('wallet'):
        tok = (request.headers.get('X-CSRF-Token', '') or
               request.headers.get('X-CSRFToken', '') or
               (request.get_json(silent=True) or {}).get('csrf_token', ''))
        # If session has no csrf_token yet (pre-dates CSRF system, or old cookie
        # without the token), generate one now and let this request through.
        # Origin + client-secret checks above already validated the caller.
        if not session.get('csrf_token'):
            session['csrf_token'] = secrets.token_hex(32)
        if not _validate_csrf(tok):
            _log_security_event('csrf_fail', session.get('wallet', 'unknown'),
                                f'bad/missing token on {request.path}')
            return jsonify({
                'error': 'CSRF validation failed',
                'logged_in': bool(session.get('wallet')),
                'hint': 'Send the token from GET /api/csrf-token in X-CSRF-Token header'
            }), 403

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

BASE         = os.path.dirname(os.path.abspath(__file__))
DM_IMAGES_DIR   = os.path.join(BASE, 'static', 'dm_images')
CHAT_IMAGES_DIR = os.path.join(BASE, 'static', 'chat_images')
os.makedirs(DM_IMAGES_DIR,   exist_ok=True)
os.makedirs(CHAT_IMAGES_DIR, exist_ok=True)
# Where the database, backups and logs live -- the one directory that has to
# survive a redeploy.
#
# DATA_DIR first, so this is not tied to any one host's convention: Railway
# mounts a volume at /data, another host may put it anywhere, and a plain
# server usually wants it outside the checkout so a git pull cannot sit on
# top of the database. /data is still honoured when it exists, and the app
# directory remains the last resort.
_DATA_DIR    = (os.getenv('DATA_DIR', '').strip()
                or ('/data' if os.path.exists('/data') else BASE))
try:
    os.makedirs(_DATA_DIR, exist_ok=True)
except Exception as _dd_err:
    print(f'[startup] DATA_DIR {_DATA_DIR!r} is not usable ({_dd_err}) — '
          f'falling back to the app directory', flush=True)
    _DATA_DIR = BASE
# Set here, not up with the other app.config lines, because the key belongs in
# DATA_DIR and that is only resolved above. Nothing between the two touches a
# session -- route decorators only register -- so this still runs long before
# the first request.
app.secret_key = _load_secret_key(_DATA_DIR)

LOG_FILE     = os.path.join(_DATA_DIR, 'trades.log')
DB_FILE        = os.path.join(_DATA_DIR, 'orcagent.db')
BACKUP_DIR     = os.path.join(_DATA_DIR, 'backups')
HEARTBEAT_FILE = os.path.join(_DATA_DIR, 'heartbeat.txt')

# ── DATA VOLUME ───────────────────────────────────────────────────────
# Defined HERE, next to the paths they read, rather than beside
# backup_database() where they are mostly used. The startup storage check
# runs long before that point in the file, and having them further down is
# what took the site off the air: _db_write_selftest() called _free_bytes()
# a hundred lines before its def, so the module raised NameError on import
# and the app never started at all.
BACKUP_KEEP          = 3               # compressed copies to retain
BACKUP_MIN_FREE_BYTES = 300 * 1024 * 1024   # refuse to write one below this

def _free_bytes(path=None) -> int:
    """Free space on the data volume, or -1 if it cannot be read."""
    try:
        return shutil.disk_usage(path or _DATA_DIR).free
    except Exception:
        return -1

def _backup_files() -> list:
    """Existing backups, newest first. Matches both the compressed files we
    write now and the plain .db ones older versions left behind, so those are
    still listed and still pruned."""
    try:
        return sorted([f for f in os.listdir(BACKUP_DIR)
                       if f.startswith('orcagent_') and (f.endswith('.db') or f.endswith('.db.gz'))],
                      reverse=True)
    except Exception:
        return []

def _prune_backups(keep: int = BACKUP_KEEP) -> int:
    """Delete all but the `keep` newest backups. Never deletes the newest
    one, whatever `keep` says -- a backup directory is worth shrinking, not
    emptying."""
    freed = 0
    for old in _backup_files()[max(keep, 1):]:
        try:
            path = os.path.join(BACKUP_DIR, old)
            freed += os.path.getsize(path)
            os.remove(path)
            print(f'[backup] pruned {old}', flush=True)
        except Exception as e:
            print(f'[backup] could not prune {old}: {e}', flush=True)
    return freed

_APP_START     = time.time()
print(f"[startup] persistent storage: {os.path.exists('/data')}  db={DB_FILE}", flush=True)

# ── SQLITE: how long a connection waits for the write lock ─────────────
# The database is already in WAL mode (set once in init_db, and stored in the
# file itself), so readers never block writers. What WAL does NOT change is
# that there can only be one WRITER at a time -- and this process has many:
# the request threads plus the bot loop, the monitor, the surge radar, the
# gas sweep and the calls-peak refresh, all on one file.
#
# When a write can't get the lock it waits `busy_timeout` and then raises
# "database is locked". Python's default is 5 seconds, which a burst of
# background writes can exceed -- that is what produced the "Database busy"
# on Make a Call. Thirty seconds is far longer than any single write here
# takes, so a caller now queues instead of failing.
#
# Applied by wrapping sqlite3.connect once, rather than editing the ~360
# call sites that open the database. Every one of them looks the function up
# on the module at call time, so they all pick this up -- including the
# background modules that import sqlite3 separately. The behaviour is
# unchanged apart from the waiting.
_sqlite3_connect = sqlite3.connect
def _sqlite_reason(e) -> tuple:
    """Turn a sqlite3.OperationalError into something worth showing.

    These errors mean very different things and want very different actions,
    but they arrive as one exception type, so a handler that assumes "locked"
    tells a user to retry a read-only filesystem forever. Only the first case
    is worth retrying; the rest need someone to look at the server, and the
    message says so instead of pretending otherwise."""
    t = str(e).lower()
    if 'locked' in t or 'busy' in t:
        return 'Database busy — try again in a moment', 503
    if 'readonly' in t or 'read-only' in t:
        return 'The database is read-only — the server storage needs attention', 500
    if 'full' in t or 'disk i/o' in t or 'no space' in t:
        return 'The server storage is full — this needs attention', 500
    if 'no such table' in t or 'no such column' in t:
        return 'Database schema is out of date on the server', 500
    # Unmapped: show it rather than inventing a cause. It is a SQLite message
    # about our own database, not anything private.
    return f'Database error: {str(e)[:90]}', 500

def _sqlite_connect_patient(*args, **kwargs):
    kwargs.setdefault('timeout', 30.0)
    conn = _sqlite3_connect(*args, **kwargs)
    try:
        conn.execute('PRAGMA busy_timeout=30000')
    except Exception:
        pass          # a connection too broken to take a pragma will fail loudly on its own
    return conn
sqlite3.connect = _sqlite_connect_patient

TAKE_PROFIT     = 0.05   # 5%  — universal take profit
BOT_BRIDGE_MAX_PER_TX  = 10.0  # USD — hardcoded, not user-configurable
BOT_BRIDGE_MAX_PER_DAY = 25.0  # USD — hardcoded, not user-configurable
NARRATIVE_MAX_PER_TX   = 10.0  # USD — hardcoded, not user-configurable
NARRATIVE_MAX_PER_DAY  = 25.0  # USD — hardcoded, not user-configurable
NARRATIVE_AGENT_GLOBAL_LIVE = False  # kill switch: while False, only ADMIN_WALLET can actually buy
# Wallets that count as "allowed" alongside ADMIN_WALLET while
# NARRATIVE_AGENT_GLOBAL_LIVE is False, and that skip NARRATIVE_MAX_PER_TX/
# NARRATIVE_MAX_PER_DAY (see _can_narrative_buy()) -- the circuit breaker
# still applies to them, same as everyone else.
NARRATIVE_UNCAPPED_WALLETS = {'Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9'}
# PUMPFUN-DEGEN pre-bond auto-buy threshold (USD, 24h volume) -- see
# _narrative_agent_process_candidate(). At/above this, a NARRATIVE_UNCAPPED_
# WALLETS pre-bond candidate that clears _narrative_safety_gate_pumpfun()
# skips get_narrative_signal() (no AI review) entirely.
NARRATIVE_PUMPFUN_VOLUME_THRESHOLD = 10000
# In-memory dedup for NARRATIVE_UNCAPPED_WALLETS' dedicated 10s fast loop
# only (see _narrative_agent_collect_new_candidates()) -- every other
# wallet's normal 15-iteration/900s _narrative_agent_cycle() check never
# touches this set and re-scans the same trending candidates every pass,
# unchanged.
_narrative_seen_mints: set = set()
STOP_LOSS       = 0.03   # 3%  — universal stop loss
EXIT_PERCENTAGE = 1.0    # sell 100% of position on any exit
CRASH_EXIT      = 0.15   # 15% — emergency exit on extreme drop
# Position-sizing risk cap: never risk more than this fraction of a wallet's
# trading SOL balance on a single position's stop-loss distance (spend *
# stop_loss = worst-case loss if SL fires cleanly). Only ever shrinks the
# existing score-based stake in user_trader_loop(), never grows it.
MAX_RISK_PCT_PER_TRADE = 0.02  # 2% of capital at risk per trade
# How many of the top qualifying (score/momentum/safety-filtered) candidates
# a scan considers for its weighted-random buy pick -- see the "Pass 2" entry
# selection in user_trader_loop(). Was 5; widened so the bot evaluates a much
# larger slice of the live market each cycle instead of only ever choosing
# among the single highest-momentum handful.
BUY_POOL_SIZE = 25
# Opt-in tiered take-profit (users.tiered_tp_enabled) -- sell TP1_SELL_FRACTION
# of the position once price reaches TP1_MULTIPLE x entry, then trail the
# remainder with TRAILING_STOP_PCT off its peak instead of the flat
# take_profit %. Off by default; see the ALTER TABLE comment for why.
TP1_MULTIPLE       = 2.0   # first target: 2x entry price
TP1_SELL_FRACTION  = 0.5   # sell 50% of the position at TP1
TRAILING_STOP_PCT  = 0.15  # trail the remainder 15% below its post-TP1 peak
MIN_MARKETCAP_USD = 15_000  # fallback only — see _min_marketcap_for_stake() below, which is
                             # what actually gates entries per-user based on their stake size

# ── TRADING ENGINE V2: user-controlled SL/TP presets + staged exits ──
# Server-side-validated bounds for a user's own stop_loss/take_profit % --
# enforced in _validate_sl_tp() regardless of preset or custom entry, since
# the frontend's own bounds (e.g. a slider's min/max) are never trusted here.
SL_PCT_MIN, SL_PCT_MAX = 1.0, 30.0    # stop loss: 1%–30%
TP_PCT_MIN, TP_PCT_MAX = 2.0, 500.0   # take profit: 2%–500%
# Named presets a user picks from Settings (see api_trading_profile()) --
# 'custom' means the user typed their own SL/TP, still clamped to the bounds
# above. trailing maps onto the existing users.tiered_tp_enabled column (see
# that column's own comment) rather than adding a second, redundant toggle.
TRADE_PROFILE_PRESETS = {
    'conservative': {'stop_loss': 3.0,  'take_profit': 10.0, 'trailing': True},
    'balanced':     {'stop_loss': 5.0,  'take_profit': 20.0, 'trailing': True},
    'aggressive':   {'stop_loss': 8.0,  'take_profit': 30.0, 'trailing': True},
}
# Staged partial take-profit (opt in via the same trailing/tiered toggle as
# TP1_MULTIPLE above, but keyed off the user's OWN take_profit % instead of a
# flat 2x-entry target): first stage sells a slice at half the user's TP
# target, second stage sells another slice at the full target, and whatever
# remains becomes a trailing runner (see TP2_TRAIL_PCT_MIN/MAX below) instead
# of being closed outright. Mirrors TP1_MULTIPLE/TP1_SELL_FRACTION's shape so
# a position missing the newer per-position snapshot (opened before this
# migration) still degrades to the old single-tier behavior.
TP_STAGE1_FRACTION_OF_TARGET = 0.5   # stage 1 fires at 0.5x the user's TP%
TP_STAGE1_SELL_FRACTION      = 0.20  # sell 20% of the position at stage 1
TP_STAGE2_FRACTION_OF_TARGET = 1.0   # stage 2 fires at 1.0x the user's TP%
TP_STAGE2_SELL_FRACTION      = 0.30  # sell another 30% of what's left after stage 1 at stage 2
# Trailing runner on whatever remains after stage 2: the trail % is derived
# from the position's own recent volatility (see _volatility_trailing_pct())
# instead of one fixed number for every token, clamped to this range.
TP2_TRAIL_PCT_MIN, TP2_TRAIL_PCT_MAX = 0.08, 0.25

# ── DYNAMIC RISK MANAGEMENT (Trading Engine V2, section 5) ── hard,
# non-negotiable pre-trade gates that apply on top of whatever SL/TP the
# user picked -- the user controls the exit strategy, not whether a clearly
# bad entry gets taken at all. Only ever REJECTS a candidate the score/
# momentum filters above already liked; never used to size or sweeten a
# trade. Scoped to the bot's own autonomous entries (main loop, copy-trade
# auto-buy, narrative agent) -- a user's own manual buy click is a
# deliberate action, not an autonomous decision this section is protecting
# them from, same reasoning get_ai_trade_decision()'s AI gate already
# follows (bot-only, never applied to manual buys).
MAX_ENTRY_PRICE_IMPACT_PCT = 0.05  # 5% -- Jupiter's own priceImpactPct already
                                    # folds route-level slippage into this one
                                    # number, so a single quote covers both
                                    # "estimated price impact" and "slippage"

# ── NET EXPECTED EDGE FILTER ── a trade's "expected gross move" here is
# deliberately NOT a market prediction -- there is no calibrated model for
# that anywhere in this codebase. It uses the trade's OWN configured
# take-profit % as the transparent stand-in for "the move this trade is
# targeting if its own thesis plays out" -- never a claim that the move
# WILL happen, and never used to size or sweeten a trade, only to reject
# ones where even hitting their own target wouldn't clear round-trip costs.
PRIORITY_FEE_PCT_ASSUMPTION = 0.001  # ~0.1% of trade size -- Jupiter's own
    # 'auto' priority fee varies with live network congestion and isn't
    # knowable ahead of the real swap quote; this is a conservative,
    # clearly-labeled placeholder, logged alongside every decision so it's
    # never mistaken for a measured figure.
MIN_EDGE_TO_COST_RATIO = 1.0  # expected_net_edge must be >= this multiple of
    # estimated_total_cost (i.e. the trade's own target must clear at least
    # 2x round-trip costs) before a candidate is allowed through. This is a
    # cost/edge sanity floor, NOT a profitability guarantee -- it says
    # nothing about the probability the target is ever reached. See the
    # trading-engine audit's finding I: no backtest exists yet to calibrate
    # this ratio against real outcomes.

# ── LOSS-STREAK THROTTLE ── the bot's own risk-management response to a run of
# losing trades: not a fixed daily $ circuit breaker (that's daily_loss_limit,
# a user-configured cap checked further down the loop) but an automatic,
# self-adjusting reaction to consecutive losses, tracked per user in
# us['loss_streak'] and updated in _record_user_trade(). This only ever
# affects Pass 2 (looking for a new entry) -- Pass 1 (monitoring/exiting
# already-open positions: stop loss, take profit, crash exit, rugpull) always
# keeps running regardless of streak state, since pausing exits while under
# stress would be exactly backwards.
LOSS_STREAK_TIGHTEN_AT  = 3     # this many losses in a row -> raise the entry bar (see qualifying loop)
LOSS_STREAK_PAUSE_AT    = 5     # this many losses in a row -> stop opening new positions for a while
LOSS_STREAK_PAUSE_SEC   = 3600  # how long that pause lasts
LOSS_STREAK_SCORE_BONUS = 1.5   # added to the score-≥5.0 qualifying floor while tightened
LOSS_STREAK_MCAP_MULT   = 2.0   # multiplier on the marketcap floor while tightened

def _min_marketcap_for_stake(stake_usd: float) -> int:
    """Tiered entry-marketcap floor: the smaller the stake, the smaller (riskier) a
    market cap is acceptable to enter, since the absolute dollar risk is small. Larger
    stakes are restricted to more established tokens. Boundaries are non-overlapping:
    a stake of exactly $5 or $50 belongs to the higher tier ("threshold reached")."""
    if stake_usd < 5:
        return 15_000
    elif stake_usd < 50:
        return 50_000
    else:
        return 100_000

# ── LEARNED ENTRY-CONDITION BIAS ── the bot's other self-training signal,
# proactive rather than reactive: instead of only responding to a run of
# losses (LOSS_STREAK_* above), this continuously nudges Pass 2's qualifying
# score for every candidate up or down based on how well THIS wallet's own
# past trades have actually done under similar entry conditions -- the entry
# bar is trained from its own realized trade history instead of being the
# same fixed number forever. Two independent dimensions feed it (liquidity
# bracket, LP-locked-% bracket), both already recorded on every close --
# see _record_user_trade(), which also invalidates both caches below the
# instant a new trade closes, so the very next scan re-learns from it
# immediately rather than waiting out the TTL.
_LIQUIDITY_TIER_BOUNDS   = (10_000, 50_000, 200_000)  # upper bound of tiers 0..2; tier 3 is "and above"
_LP_LOCKED_TIER_BOUNDS   = (70, 90)                   # upper bound of tiers 0..1; tier 2 is "90%+"
LEARNED_BIAS_MIN_SAMPLES = 5    # a bracket needs at least this many of the wallet's own closed trades before it's trusted
LEARNED_BIAS_MAX         = 2.0  # clamp per dimension -- neither can move the score gate by more than +-2.0
LEARNED_BIAS_SCALE       = 4.0  # (bracket win-rate - overall win-rate), which is in [-1, 1], times this = raw bias
LEARNED_BIAS_TTL_SEC     = 300  # fallback staleness limit -- normally moot since a trade close invalidates it directly

def _liquidity_tier(liquidity: float) -> int:
    for i, bound in enumerate(_LIQUIDITY_TIER_BOUNDS):
        if liquidity < bound:
            return i
    return len(_LIQUIDITY_TIER_BOUNDS)

def _lp_locked_tier(lp_locked_pct: float) -> int:
    for i, bound in enumerate(_LP_LOCKED_TIER_BOUNDS):
        if lp_locked_pct < bound:
            return i
    return len(_LP_LOCKED_TIER_BOUNDS)

def _bracket_bias_from_rows(rows) -> dict:
    """Shared by _learned_liquidity_bias()/_learned_lp_bias(): rows is an
    iterable of (bracket_index, pnl). Returns {bracket_index: score_bias} --
    see _learned_liquidity_bias()'s docstring for what the numbers mean."""
    brackets: dict = {}
    total_wins = total_n = 0
    for bracket, pnl in rows:
        d = brackets.setdefault(bracket, {'wins': 0, 'n': 0})
        d['n'] += 1
        total_n += 1
        if pnl > 0:
            d['wins'] += 1
            total_wins += 1
    bias = {}
    if total_n >= LEARNED_BIAS_MIN_SAMPLES:
        overall_wr = total_wins / total_n
        for bracket, d in brackets.items():
            if d['n'] < LEARNED_BIAS_MIN_SAMPLES:
                continue
            wr = d['wins'] / d['n']
            bias[bracket] = max(-LEARNED_BIAS_MAX, min(LEARNED_BIAS_MAX, (wr - overall_wr) * LEARNED_BIAS_SCALE))
    return bias

def _learned_liquidity_bias(user_id: int) -> dict:
    """{tier_index: score_bias}, learned from this user's own closed trades
    (trades.entry_liquidity + trades.pnl -- already recorded on every close,
    no new data collection needed). A tier this wallet has actually won more
    often than its overall average gets a positive bias (helps a marginal
    candidate in that bracket clear the qualifying floor); a tier that's lost
    more than average gets a negative one. A tier without
    LEARNED_BIAS_MIN_SAMPLES closed trades yet gets no entry at all -- not
    enough evidence to trust either way, so it's left neutral."""
    _cached = _learned_bias_cache.get(user_id)
    if _cached and time.time() - _cached[0] < LEARNED_BIAS_TTL_SEC:
        return _cached[1]
    conn = sqlite3.connect(DB_FILE)
    try:
        rows = conn.execute(
            'SELECT entry_liquidity, pnl FROM trades '
            'WHERE user_id=? AND entry_liquidity IS NOT NULL AND entry_liquidity > 0 AND pnl IS NOT NULL',
            (user_id,)
        ).fetchall()
    finally:
        conn.close()
    bias = _bracket_bias_from_rows((_liquidity_tier(liq), pnl) for liq, pnl in rows)
    _learned_bias_cache[user_id] = (time.time(), bias)
    return bias

def _learned_lp_bias(user_id: int) -> dict:
    """Same idea as _learned_liquidity_bias(), bucketed by LP-locked-%
    instead of liquidity (trades.entry_lp_locked_pct). Since the bot already
    hard-requires >=50% LP locked before ever buying, every bracket here
    starts from that floor -- this only distinguishes "barely cleared the
    bar" from "fully locked/burned" once there's enough evidence either way
    actually matters for this wallet."""
    _cached = _learned_lp_bias_cache.get(user_id)
    if _cached and time.time() - _cached[0] < LEARNED_BIAS_TTL_SEC:
        return _cached[1]
    conn = sqlite3.connect(DB_FILE)
    try:
        rows = conn.execute(
            'SELECT entry_lp_locked_pct, pnl FROM trades '
            'WHERE user_id=? AND entry_lp_locked_pct IS NOT NULL AND pnl IS NOT NULL',
            (user_id,)
        ).fetchall()
    finally:
        conn.close()
    bias = _bracket_bias_from_rows((_lp_locked_tier(pct), pnl) for pct, pnl in rows)
    _learned_lp_bias_cache[user_id] = (time.time(), bias)
    return bias

def _invalidate_learned_bias(user_id: int) -> None:
    """Called right after a trade closes (see _record_user_trade()) so the
    next Pass 2 scan learns from it immediately instead of waiting up to
    LEARNED_BIAS_TTL_SEC for the cache to go stale on its own."""
    _learned_bias_cache.pop(user_id, None)
    _learned_lp_bias_cache.pop(user_id, None)

WALLET_ADDRESS   = os.environ.get('WALLET_ADDRESS', '')
USDC_MINT        = 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v'
SOL_MINT         = 'So11111111111111111111111111111111111111112'
SOLANA_RPC       = 'https://api.mainnet-beta.solana.com'
SOLANA_RPC_URL   = os.environ.get('SOLANA_RPC_URL', '')   # set in the env file — overrides all fallbacks
HELIUS_RPC       = os.environ.get('HELIUS_RPC', '')        # full Helius URL e.g. https://mainnet.helius-rpc.com/?api-key=xxx
HELIUS_API_KEY   = os.environ.get('HELIUS_API_KEY', '')
# ── BSC (multi-chain) config — mirrors the Solana RPC pattern above ──
BSC_CHAIN_ID     = 56
BSC_RPC          = 'https://bsc-dataseed.binance.org/'      # public fallback, Binance-operated
BSC_RPC_URL      = os.environ.get('BSC_RPC_URL', '')        # set in the env file — overrides fallback (Alchemy/Ankr/etc)
USDC_BSC_ADDR    = '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d'  # USDC (BEP-20), 18 decimals -- NOT 6 like Solana/Ethereum
ZEROX_API_KEY    = os.environ.get('ZEROX_API_KEY', '')      # required for BSC swaps -- get one at dashboard.0x.org
BNB_NATIVE_ADDR  = '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE'  # 0x's sentinel address for the native gas token
# OWNER_WALLET vs ADMIN_WALLET — deliberately two separate constants, not
# duplication (checked/confirmed against production 2026-08-08: same address
# in practice, but that's a deployment fact, not something the code enforces
# or should assume):
#   - OWNER_WALLET: env-configurable, used by _is_owner() for general owner
#     checks, and as the destination for regular trading-fee recovery. Can be
#     blank if the env var is never set (see the startup warning below).
#   - ADMIN_WALLET: hardcoded, intentionally NOT tied to any env var, used
#     specifically where a misconfigured-or-blank OWNER_WALLET must never be
#     able to cause harm: it's the real on-chain destination
#     _verify_promotion_payment() checks incoming promotion payments against,
#     the sole wallet allowed to use /api/promote/<id>/simulate-confirm's
#     payment-bypass, and a "constant super-admin" that can't be demoted or
#     removed from the role system by another admin (see the role-removal
#     guards further down). Don't consolidate this into OWNER_WALLET --
#     that would make all of the above depend on a value that can be blank
#     or changed via deploy config.
OWNER_WALLET     = os.environ.get('OWNER_WALLET', '')
ADMIN_WALLET     = 'HC5ahspSox3XRmDbzXjXVoAASuY89RCmGUKwp87FRJS5'

# Every wallet with FULL owner rights -- fee collection, key rotation, the
# gas sponsor panel, force-close, all of it.
#
# OWNER_WALLET itself may be a comma-separated list, and OWNER_WALLETS can
# add more, so ownership can be granted or revoked in the env file without
# a deploy. The operator's own wallet is listed below as well so the platform
# always has a working owner even if that env var is blank or stale -- which
# is exactly the state that made every admin button answer "Unauthorized".
#
# Publishing these addresses is not a credential leak: an address only names
# an account. Reaching any of this still requires a signature from that
# wallet's private key (see _authenticated_wallet), which is never here.
_BUILTIN_OWNER_WALLETS = ['Cdn8WftaYycdudV9yeeQPY1A1Tgo1bMa9eV4Tv9SeAM9']
OWNER_WALLETS = {
    w.strip() for w in (
        OWNER_WALLET.split(',')
        + os.environ.get('OWNER_WALLETS', '').split(',')
        + _BUILTIN_OWNER_WALLETS
    ) if w.strip()
}
WEBAUTHN_RP_ID   = os.environ.get('WEBAUTHN_RP_ID', 'orcagent.fun')
WEBAUTHN_RP_NAME = 'OrcAgent'
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '')
VAPID_PUBLIC_KEY  = os.getenv('VAPID_PUBLIC_KEY', '')
VAPID_CLAIMS      = {'sub': 'mailto:admin@orcagent.fun'}
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
JUPITER_PROXY    = os.environ.get('JUPITER_PROXY_URL', '').rstrip('/')
PROXY_SECRET     = os.environ.get('JUPITER_PROXY_SECRET', '')
print(f'[startup] JUPITER_PROXY_URL = {(JUPITER_PROXY[:40] + "...") if len(JUPITER_PROXY) > 40 else (JUPITER_PROXY or "(not set — using api.jup.ag directly)")}', flush=True)
# Optional shared secret the frontend echoes back on every mutating request.
# Defense-in-depth against scripted bots that POST straight to the API without ever
# loading the page (and therefore never seeing this value). Skipped entirely when unset,
# so local/dev deployments without the env var keep working unchanged.
API_SHARED_SECRET  = os.environ.get('API_SHARED_SECRET', '')
FEE_RATE_DEFAULT = 0.05  # 5% performance fee on profitable trades only
FEE_RATE_TXN     = 0.0075  # 0.75% transaction fee, charged on BOTH the buy and the sell

# Whether the manual EVM buy runs through the trade engine, where the amount
# a user enters is the MAXIMUM they spend and the purchase is what remains
# after gas, the fee and the slippage reserve. Off puts that one route back on
# the pre-engine path, which swaps the full amount and charges the fee on top
# -- a way back if the engine misbehaves in production, not an equal option.
TRADE_ENGINE_MANUAL_EVM = os.getenv('TRADE_ENGINE_MANUAL_EVM', '1').strip() not in ('0', 'false', 'False', '')
                            # leg of every trade (see _charge_txn_fee()) -- so a full
                            # round-trip pays 1.5% total, split as two separate 0.75%
                            # charges rather than one combined charge at close.

def _get_fee_rate():
    try:
        conn = sqlite3.connect(DB_FILE)
        row = conn.execute("SELECT value FROM platform_settings WHERE key='fee_rate'").fetchone()
        conn.close()
        return float(row[0]) if row else FEE_RATE_DEFAULT
    except Exception:
        return FEE_RATE_DEFAULT
FEE_WALLET       = 'HC5ahspSox3XRmDbzXjXVoAASuY89RCmGUKwp87FRJS5'  # fixed fee recipient (independent of admin role)
# BSC fee recipient -- a *separate* constant from FEE_WALLET on purpose: that's a
# base58 Solana address and is not a valid EVM recipient in any sense (wrong
# alphabet, wrong length, no relation to a BSC keypair). Left blank pending the
# real BSC-format address -- _charge_bsc_txn_fee() no-ops (logs and skips) rather
# than sending anywhere while this is unset, so no fee silently goes missing to
# the wrong address.
BSC_FEE_WALLET   = '0x4f187411023338E717D68c089855372997ef4640'  # fixed BSC fee recipient -- public address only, no key held anywhere

# ── Other EVM chains (Base, Arbitrum, Polygon, Robinhood Chain) ─────────────
# A secp256k1 (EVM) keypair is chain-agnostic -- the SAME address/private key
# already generated for BSC (ensure_bsc_wallet, encrypted_private_key_bsc) is
# valid on every chain below too, exactly like one MetaMask account works on
# any EVM network. So there is deliberately no separate wallet/key per chain
# here, and BSC_FEE_WALLET above is reused as-is for all of them (also just a
# public EVM address, valid everywhere). Each entry's `usdc` is that chain's
# own primary USD stablecoin -- NATIVE Circle-issued USDC for Base/Arbitrum/
# Polygon (verified against that chain's own official block explorer:
# basescan.org, arbiscan.io, polygonscan.com -- not a bridged variant like
# Arbitrum's USDC.e or BSC's Binance-Peg USDC, which is why BSC stays on its
# own USDC_BSC_ADDR/18-decimals path above rather than joining this dict).
# Robinhood Chain has no USDC at all -- bridging USDC there converts it to
# USDG (Global Dollar, issued by Paxos), which is what `usdc` actually holds
# for that entry; `usdc_symbol` is what every USDC-labeled UI string and log
# line should say instead, so a Robinhood Chain trade is never mislabeled as
# spending "USDC" when it's really USDG (address verified against Robinhood
# Chain's own explorer, robinhoodchain.blockscout.com; router/DEX routing
# itself still goes through 0x's Swap API below like every other chain here,
# not a hand-built Uniswap Universal Router integration, since 0x announced
# day-1 support for Robinhood Chain at its mainnet launch). rpc_url falls
# back to a well-known public RPC exactly like BSC_RPC does; an *_RPC_URL
# env var overrides it the same way BSC_RPC_URL does, for a paid/rate-limit-
# free provider (Alchemy, Ankr, etc.) in production. dex_chain is the
# DexScreener chainId slug for that network (used by the scanner's discovery
# queries), zerox_chain_id is what _get_0x_quote() passes 0x's API to route
# the swap itself.
EVM_CHAINS = {
    'bsc': {
        'chain_id': BSC_CHAIN_ID, 'native_symbol': 'BNB', 'usdc_symbol': 'USDC',
        'rpc_url': BSC_RPC_URL or BSC_RPC, 'usdc': USDC_BSC_ADDR,
        'explorer': 'https://bscscan.com', 'dex_chain': 'bsc', 'zerox_chain_id': BSC_CHAIN_ID,
    },
    'base': {
        'chain_id': 8453, 'native_symbol': 'ETH', 'usdc_symbol': 'USDC',
        'rpc_url': os.environ.get('BASE_RPC_URL', '') or 'https://mainnet.base.org',
        'usdc': '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913',
        'explorer': 'https://basescan.org', 'dex_chain': 'base', 'zerox_chain_id': 8453,
    },
    'arbitrum': {
        'chain_id': 42161, 'native_symbol': 'ETH', 'usdc_symbol': 'USDC',
        'rpc_url': os.environ.get('ARBITRUM_RPC_URL', '') or 'https://arb1.arbitrum.io/rpc',
        'usdc': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
        'explorer': 'https://arbiscan.io', 'dex_chain': 'arbitrum', 'zerox_chain_id': 42161,
    },
    'polygon': {
        'chain_id': 137, 'native_symbol': 'POL', 'usdc_symbol': 'USDC',
        'rpc_url': os.environ.get('POLYGON_RPC_URL', '') or 'https://polygon-rpc.com',
        'usdc': '0x3c499c542cef5e3811e1192ce70d8cc03d5c3359',
        'explorer': 'https://polygonscan.com', 'dex_chain': 'polygon', 'zerox_chain_id': 137,
    },
    'robinhood': {
        'chain_id': 4663, 'native_symbol': 'ETH', 'usdc_symbol': 'USDG',
        'rpc_url': os.environ.get('ROBINHOOD_RPC_URL', '') or 'https://rpc.mainnet.chain.robinhood.com',
        'usdc': '0x5fc5360D0400a0Fd4f2af552ADD042D716F1d168',  # USDG (Global Dollar) -- see usdc_symbol note above
        'explorer': 'https://robinhoodchain.blockscout.com', 'dex_chain': 'robinhood', 'zerox_chain_id': 4663,
    },
}
EVM_CHAIN_FEE_WALLET = BSC_FEE_WALLET  # same EVM address works as the fee recipient on every chain above

# What a user is told they are spending. Always USDC, on every chain.
#
# This is NOT the same question as `usdc_symbol`, and conflating the two is
# what put "YOU SPEND AT MOST USDG" on the buy panel. There are two different
# facts here and they have different audiences:
#
#   usdc_symbol      the token that actually moves on that chain. On
#                    Robinhood Chain that is USDG (Global Dollar), because no
#                    USDC exists there at all. Logs, the swap routing and
#                    anything you would take to a block explorer need this
#                    one, or a transaction becomes impossible to find.
#
#   this function    the currency the USER put in and is spending. That is
#                    USDC everywhere, including Robinhood Chain, because the
#                    app bridges their USDC there and it converts to USDG on
#                    arrival (see _maybe_start_auto_bridge_for_buy). They
#                    never hold, choose, or deposit USDG -- it is an
#                    implementation detail of one chain's plumbing.
#
# So this is not a relabelling of USDG as USDC. It is naming the thing the
# person actually spent, and leaving the on-chain token named accurately
# where the on-chain token is what matters.
def user_currency_label(chain: str, base_currency: str = None) -> str:
    """The currency to show a user for a trade on this chain.

    Only Solana in SOL mode is not USDC, and that is a real user choice --
    SOLANA_BASE_CURRENCY. Everything else is USDC, whatever token the chain
    settles in underneath."""
    if (chain or '').lower() == 'solana' and (base_currency or '').upper() == 'SOL':
        return 'SOL'
    return 'USDC'

PROMOTION_PRICE_USD_DEFAULT = 70.0
PROMOTION_PRICE_SOL_FALLBACK = 0.42  # used only if the SOL/USD rate isn't available yet
PROMOTION_DURATION_HOURS_DEFAULT = 14

def _get_promotion_price_sol():
    try:
        conn = sqlite3.connect(DB_FILE)
        row = conn.execute("SELECT value FROM platform_settings WHERE key='promotion_price_usd'").fetchone()
        conn.close()
        usd_price = float(row[0]) if row else PROMOTION_PRICE_USD_DEFAULT
    except Exception:
        usd_price = PROMOTION_PRICE_USD_DEFAULT
    if not _sol_price_usd:
        return PROMOTION_PRICE_SOL_FALLBACK
    return round(usd_price / _sol_price_usd, 3)

def _get_promotion_duration_hours():
    try:
        conn = sqlite3.connect(DB_FILE)
        row = conn.execute("SELECT value FROM platform_settings WHERE key='promotion_duration_hours'").fetchone()
        conn.close()
        return float(row[0]) if row else PROMOTION_DURATION_HOURS_DEFAULT
    except Exception:
        return PROMOTION_DURATION_HOURS_DEFAULT

# Ordered list of RPC endpoints for claim_sol / blockhash / send_raw queries.
# Priority: SOLANA_RPC_URL → HELIUS_RPC → HELIUS_API_KEY → public fallbacks
def _build_claim_rpcs() -> list:
    rpcs = []
    if SOLANA_RPC_URL:
        rpcs.append(SOLANA_RPC_URL)
    if HELIUS_RPC:
        rpcs.append(HELIUS_RPC)
    if HELIUS_API_KEY:
        rpcs.append(f'https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}')
    rpcs.append('https://solana-mainnet.g.alchemy.com/v2/demo')
    rpcs.append('https://mainnet.helius-rpc.com/?api-key=demo')
    rpcs.append('https://api.mainnet-beta.solana.com')
    return rpcs
CLAIM_SOL_RPCS = _build_claim_rpcs()
def _rpc_label(url: str) -> str:
    if 'helius' in url: return 'Helius'
    if 'alchemy' in url: return 'Alchemy'
    if 'mainnet-beta' in url: return 'mainnet-beta'
    # Strip query string before truncating — query params may contain API keys
    return url.split('?')[0][:40]
print(f'[rpc] CLAIM_SOL_RPCS ({len(CLAIM_SOL_RPCS)} endpoints): '
      + ', '.join(_rpc_label(u) for u in CLAIM_SOL_RPCS), flush=True)

# ── FERNET ENCRYPTION ──
# ENCRYPTION_KEY must be set as an environment variable. No fallback — app refuses to start
# without it to ensure all stored private keys are always properly encrypted.
_enc_key_str = os.environ.get('ENCRYPTION_KEY', '').strip()
if not _enc_key_str:
    print('CRITICAL: ENCRYPTION_KEY env var is not set. Refusing to start.', flush=True)
    print('         Generate one: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"', flush=True)
    sys.exit(1)

try:
    _fernet = Fernet(_enc_key_str.encode())
except Exception:
    print('CRITICAL: ENCRYPTION_KEY is not a valid Fernet key. Refusing to start.', flush=True)
    sys.exit(1)

# Non-reversible fingerprint of ENCRYPTION_KEY — safe to log (unlike the key itself).
# Logged at startup and alongside every encrypt/decrypt so a key mismatch between when a
# private key was *saved* and when it's later *decrypted* (e.g. ENCRYPTION_KEY rotated or
# differs between environments) shows up immediately as mismatched fingerprints in the logs.
_enc_key_fingerprint = hashlib.sha256(_enc_key_str.encode()).hexdigest()[:8]
print(f'[startup] ENCRYPTION_KEY fingerprint: {_enc_key_fingerprint} (sha256 prefix — not the key itself)', flush=True)

def _wallet_fernet(wallet: str) -> Fernet:
    """Derive a wallet-specific Fernet key via HMAC-SHA256(ENCRYPTION_KEY, wallet_address)."""
    derived = hmac.digest(_enc_key_str.encode(), wallet.encode(), 'sha256')
    return Fernet(base64.urlsafe_b64encode(derived))

def encrypt_private_key(raw: str, wallet: str) -> str:
    """Double-encrypt: Layer 1 = ENCRYPTION_KEY Fernet, Layer 2 = wallet-derived Fernet.
    Result is prefixed with 'v2:' to distinguish from legacy single-layer ciphertext."""
    l1 = _fernet.encrypt(raw.encode())
    l2 = _wallet_fernet(wallet).encrypt(l1)
    short_w = (wallet[:6] + '...' + wallet[-4:]) if len(wallet) >= 10 else wallet
    print(f'[encrypt] wallet={short_w} enc_key_fp={_enc_key_fingerprint}', flush=True)
    return 'v2:' + l2.decode()

def decrypt_private_key(enc: str, wallet: str) -> str:
    """Decrypt v2 (double-encrypted) or legacy v1 (single Fernet layer) private key.
    Logs the specific failure category (bad input / malformed ciphertext / wrong key or
    corrupted blob / encoding issue) before re-raising, so the real cause is visible in
    prod logs instead of a generic failure. Never logs key or plaintext material."""
    short_w  = (wallet[:6] + '...' + wallet[-4:]) if len(wallet) >= 10 else wallet
    blob_len = len(enc) if isinstance(enc, str) else -1
    is_v2    = isinstance(enc, str) and enc.startswith('v2:')
    try:
        if not isinstance(enc, str) or not enc:
            raise ValueError(f'encrypted blob is {"empty" if enc == "" else type(enc).__name__}, expected non-empty str')
        if is_v2:
            l1 = _wallet_fernet(wallet).decrypt(enc[3:].encode())
            return _fernet.decrypt(l1).decode()
        return _fernet.decrypt(enc.encode()).decode()  # legacy v1 — migrated on next save
    except InvalidToken:
        print(f'[decrypt] ✗ InvalidToken  wallet={short_w} v2={is_v2} blob_len={blob_len} '
              f'enc_key_fp={_enc_key_fingerprint} — either ENCRYPTION_KEY does not match the key '
              f'used to encrypt this blob (compare fingerprints against the [encrypt] log line '
              f'for this wallet), or the ciphertext is corrupted/tampered.', flush=True)
        raise
    except (binascii.Error, ValueError) as e:
        print(f'[decrypt] ✗ {type(e).__name__}  wallet={short_w} v2={is_v2} blob_len={blob_len} '
              f'— malformed ciphertext / wrong key format: {e}', flush=True)
        raise
    except UnicodeDecodeError as e:
        print(f'[decrypt] ✗ UnicodeDecodeError  wallet={short_w} v2={is_v2} blob_len={blob_len} '
              f'— decrypted bytes are not valid UTF-8 text (encoding issue): {e}', flush=True)
        raise
    except Exception as e:
        print(f'[decrypt] ✗ Unexpected {type(e).__name__}  wallet={short_w} v2={is_v2} blob_len={blob_len}: {e}', flush=True)
        raise

def encrypt_x_token(raw: str, wallet: str) -> str:
    """Encrypt an X (Twitter) OAuth access/refresh token the same way trading
    private keys are (ENCRYPTION_KEY Fernet + wallet-derived Fernet), so a DB
    compromise alone can't be used to post as a user or mint fresh tokens via
    refresh indefinitely. Prefixed 'v2:' to distinguish from the plaintext
    tokens stored before this was added -- see decrypt_x_token()."""
    l1 = _fernet.encrypt(raw.encode())
    l2 = _wallet_fernet(wallet).encrypt(l1)
    return 'v2:' + l2.decode()

def decrypt_x_token(enc: str, wallet: str) -> str:
    """Decrypt a 'v2:'-prefixed X token. Every token stored before encryption
    was added is bare plaintext with no prefix -- returned unchanged, which is
    the whole migration path (no separate backfill needed for tokens this
    function happens to touch; _encrypt_legacy_x_tokens() proactively
    encrypts the rest at startup)."""
    if not isinstance(enc, str) or not enc.startswith('v2:'):
        return enc
    l1 = _wallet_fernet(wallet).decrypt(enc[3:].encode())
    return _fernet.decrypt(l1).decode()

# ── EVM TRADING WALLET (BSC, Base, Arbitrum, Polygon -- see EVM_CHAINS) ──
# A user's EVM trading wallet is a separate, server-generated secp256k1
# keypair -- it is NOT derived from their Solana wallet in any way (the two
# key types are cryptographically unrelated). It's encrypted with the exact
# same double-Fernet scheme as the Solana key (see encrypt_private_key()
# above), keyed off the user's Solana wallet_address as their stable
# identity across chains. Named/stored as "bsc" (bsc_wallet_address,
# encrypted_private_key_bsc) from when BSC was the only other chain --
# unchanged since an EVM address/key is chain-agnostic (the exact same one
# is valid on Base/Arbitrum/Polygon too, precisely like one MetaMask account
# already works across every EVM network), so there's nothing chain-specific
# to actually rename here, just this one shared wallet reused everywhere in
# EVM_CHAINS.
def generate_bsc_wallet() -> tuple[str, str]:
    """Returns (address, private_key_hex). Never logs the private key."""
    acct = _EvmAccount.create()
    return acct.address, acct.key.hex()

def ensure_bsc_wallet(conn, user_id: int, wallet_address: str) -> str:
    """Idempotent: creates and stores this user's EVM trading wallet (shared
    across every chain in EVM_CHAINS) if they don't already have one, and
    returns the address either way."""
    row = conn.execute(
        'SELECT bsc_wallet_address, encrypted_private_key_bsc FROM users WHERE id=?',
        (user_id,)
    ).fetchone()
    if row and row[0]:
        return row[0]
    bsc_address, bsc_pk_hex = generate_bsc_wallet()
    encrypted = encrypt_private_key(bsc_pk_hex, wallet_address)
    conn.execute(
        'UPDATE users SET bsc_wallet_address=?, encrypted_private_key_bsc=? WHERE id=?',
        (bsc_address, encrypted, user_id)
    )
    conn.commit()
    print(f'[bsc] created trading wallet {bsc_address[:8]}... for user_id={user_id}', flush=True)
    return bsc_address

_w3_by_chain: dict = {}
def _get_web3(chain: str = 'bsc'):
    """Lazily-constructed, per-chain Web3 instance (cached by chain so this
    never reconnects on every call). `chain` is a key into EVM_CHAINS --
    defaults to 'bsc' so every pre-existing call site (which never passed
    this argument) keeps talking to the exact same RPC it always did."""
    global _w3_by_chain
    if chain not in _w3_by_chain:
        from web3 import Web3
        cfg = EVM_CHAINS[chain]
        _w3_by_chain[chain] = Web3(Web3.HTTPProvider(cfg['rpc_url'], request_kwargs={'timeout': 8}))
    return _w3_by_chain[chain]

# Minimal ERC20/BEP20 ABI -- just the two read-only calls we actually need,
# not the full standard. Keeps this dependency-free of any ABI-fetching step.
_ERC20_MIN_ABI = [
    {'constant': True, 'inputs': [{'name': '_owner', 'type': 'address'}],
     'name': 'balanceOf', 'outputs': [{'name': 'balance', 'type': 'uint256'}],
     'type': 'function'},
    {'constant': True, 'inputs': [], 'name': 'decimals',
     'outputs': [{'name': '', 'type': 'uint8'}], 'type': 'function'},
]

def get_evm_native_balance(address: str, chain: str = 'bsc') -> float:
    """Native gas-token balance (BNB/ETH/POL depending on `chain`), in whole
    units not wei."""
    w3 = _get_web3(chain)
    wei = w3.eth.get_balance(w3.to_checksum_address(address))
    return float(w3.from_wei(wei, 'ether'))

def get_evm_usdc_balance(address: str, chain: str = 'bsc') -> float:
    """USDC balance on `chain`. Reads decimals() from the contract itself
    rather than assuming 6 -- BSC's Binance-Peg USDC is 18 decimals, not 6
    like the native Circle USDC on every other chain in EVM_CHAINS, and this
    one read avoids hardcoding that (or any other chain's) decimals wrong."""
    w3 = _get_web3(chain)
    contract = w3.eth.contract(address=w3.to_checksum_address(EVM_CHAINS[chain]['usdc']), abi=_ERC20_MIN_ABI)
    raw = contract.functions.balanceOf(w3.to_checksum_address(address)).call()
    decimals = contract.functions.decimals().call()
    return raw / (10 ** decimals)

def get_bnb_balance(address: str) -> float:
    """Backward-compatible alias -- every pre-existing call site expects this
    exact name/signature for BSC specifically."""
    return get_evm_native_balance(address, 'bsc')

def get_bsc_usdc_balance(address: str) -> float:
    """Backward-compatible alias -- see get_bnb_balance() above."""
    return get_evm_usdc_balance(address, 'bsc')

def get_evm_balances(address: str, chain: str = 'bsc') -> dict:
    """Both balances in one call, with independent failure handling -- a
    slow/down RPC for one shouldn't blank out the other."""
    native_key = EVM_CHAINS[chain]['native_symbol'].lower()
    result = {native_key: 0.0, 'usdc': 0.0, 'error': None}
    try:
        result[native_key] = get_evm_native_balance(address, chain)
    except Exception as e:
        print(f'[{chain}] get_evm_native_balance failed for {address[:8]}...: {e}', flush=True)
        result['error'] = f'{native_key}_fetch_failed'
    try:
        result['usdc'] = get_evm_usdc_balance(address, chain)
    except Exception as e:
        print(f'[{chain}] get_evm_usdc_balance failed for {address[:8]}...: {e}', flush=True)
        result['error'] = result['error'] or 'usdc_fetch_failed'
    return result

def get_bsc_balances(address: str) -> dict:
    """Backward-compatible alias -- same {'bnb', 'usdc', 'error'} shape every
    pre-existing caller (e.g. /api/bsc/balance) already expects, since
    EVM_CHAINS['bsc']['native_symbol'].lower() == 'bnb'."""
    return get_evm_balances(address, 'bsc')

# ── PERFORMANCE FEE COLLECTION ──
def send_sol_fee(from_privkey: str, to_wallet_str: str, amount_sol: float) -> str:
    """Native SOL transfer via System Program — no ATA, no SPL, just lamports."""
    from solders.keypair import Keypair as _KP
    from solders.pubkey import Pubkey
    from solders.instruction import Instruction, AccountMeta
    from solders.transaction import Transaction
    from solders.hash import Hash as SolHash

    SYS_PROG = Pubkey.from_string('11111111111111111111111111111111')
    keypair  = _KP.from_base58_string(from_privkey)
    sender   = keypair.pubkey()
    receiver = Pubkey.from_string(to_wallet_str)
    lamports = int(amount_sol * 1_000_000_000)

    # System Program Transfer: u32 discriminant=2 + u64 lamports (little-endian)
    ix = Instruction(
        program_id=SYS_PROG,
        accounts=[
            AccountMeta(sender,   is_signer=True,  is_writable=True),
            AccountMeta(receiver, is_signer=False, is_writable=True),
        ],
        data=struct.pack('<IQ', 2, lamports),
    )

    bh = requests.post(SOLANA_RPC, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'getLatestBlockhash', 'params': [],
    }, timeout=10).json()['result']['value']['blockhash']

    tx = Transaction.new_signed_with_payer([ix], sender, [keypair], SolHash.from_string(bh))

    encoded = base64.b64encode(bytes(tx)).decode()
    res = requests.post(SOLANA_RPC, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'sendTransaction',
        'params': [encoded, {'encoding': 'base64', 'skipPreflight': False}],
    }, timeout=30).json()
    if 'error' in res:
        raise Exception('Fee TX: ' + str(res['error']))
    return res.get('result', str(res))

# ── INPUT VALIDATION ──
_SOLANA_ADDR_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
_SOLANA_KEY_RE  = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{44,88}$')
_FEED_VIEW_ID_RE = re.compile(r'^([pt])(\d+)$')   # feed_posts 'p<id>' / trades 't<id>'
_EVM_ADDR_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

def is_valid_solana_address(addr: str) -> bool:
    return bool(_SOLANA_ADDR_RE.match(addr or ''))

def is_valid_evm_address(addr: str) -> bool:
    return bool(_EVM_ADDR_RE.match(addr or ''))

# ── the chains a token can live on ───────────────────────────────────────
# Built from EVM_CHAINS rather than typed out a second time: a chain added
# there then shows up everywhere this list is offered, instead of quietly
# going missing. This codebase has twice been bitten by a second copy of a
# chain/rule list drifting out of step with the first.
TOKEN_CHAINS = ('solana',) + tuple(EVM_CHAINS.keys())

CHAIN_DISPLAY_NAMES = {
    'solana':    'Solana',
    'bsc':       'BNB Chain',
    'base':      'Base',
    'arbitrum':  'Arbitrum',
    'polygon':   'Polygon',
    'robinhood': 'Robinhood Chain',
}

def chain_display_name(chain: str) -> str:
    return CHAIN_DISPLAY_NAMES.get(chain, (chain or '').replace('_', ' ').title())

def token_address_placeholder(chain: str) -> str:
    return 'Solana mint address' if chain == 'solana' else '0x…'

def is_valid_token_address(addr: str, chain: str) -> bool:
    """Whether an address is well-formed FOR A GIVEN CHAIN.

    The chain is not optional context here. Every EVM chain shares one
    address format, so "is this a valid token address" has no answer on its
    own -- 0x… is equally well-formed on BNB Chain and on Base, and only the
    chain says which token a member would actually be verifying.
    """
    if chain == 'solana':
        return is_valid_solana_address(addr)
    if chain in EVM_CHAINS:
        return is_valid_evm_address(addr)
    return False

def is_valid_solana_private_key(key: str) -> bool:
    key = (key or '').strip()
    if _SOLANA_KEY_RE.match(key):
        return True
    if key.startswith('[') and key.endswith(']'):
        try:
            arr = json.loads(key)
            return (isinstance(arr, list) and len(arr) in (32, 64)
                    and all(isinstance(b, int) and 0 <= b <= 255 for b in arr))
        except Exception:
            pass
    return False

# ── HONEYPOT GATE (logging only — no IP blocking) ──
# Owner/trusted IPs — set via env var, comma-separated (e.g. "1.2.3.4,5.6.7.8").
_OWNER_IPS = frozenset(
    ip.strip() for ip in os.environ.get('OWNER_IP_WHITELIST', '').split(',') if ip.strip()
)

# Sensitive paths that are hard-blocked for bot/empty User-Agents
_BOT_BLOCKED_PATHS = frozenset({
    '/api/login_password',
    '/api/instant-trade',
    '/api/wallet/send',
    '/api/connect-wallet',
})

# User-Agent patterns that indicate automated clients, not real browsers
_BOT_UA_RE = re.compile(
    r'curl|python-requests|python-urllib|scrapy|wget|httpx|aiohttp|bot|spider|crawl',
    re.IGNORECASE,
)

# Any request path matching this is a known scanner/exploit probe — never legitimate
# traffic for this app. Dotfile segments (e.g. /.env, /.git/config) are blocked except
# /.well-known/ (used for ACME/domain-verification). wp-* and config.php cover the most
# common CMS-scanner probes.
_BLOCKED_PROBE_RE = re.compile(
    r'(^|/)\.(?!well-known(/|$))[^/]*'
    r'|/wp-admin(/|$)'
    r'|/wp-login\.php$'
    r'|/config\.php$'
    r'|/phpinfo(\.php)?$',
    re.IGNORECASE,
)

# Common SQL-injection / XSS / path-traversal signatures in request bodies or query
# strings. Logging only — never blocks, since legitimate input could rarely overlap
# (e.g. a token symbol containing "or"). Lets the security_log surface real attack
# attempts without risking false-positive lockouts of real users.
_SUSPICIOUS_INPUT_RE = re.compile(
    r"union\s+select|select\s+.*\s+from|insert\s+into|drop\s+table|"
    r"'\s*or\s*'?1'?\s*=\s*'?1|;\s*--|<script[\s>]|javascript:|onerror\s*=|"
    r"\.\./\.\.|%00|\bexec\s*\(",
    re.IGNORECASE,
)

# ── RATE LIMITING ──
_rl_lock: threading.Lock = threading.Lock()
_rl_hits: dict           = {}
_rl_blocked: dict        = {}  # key → list of block timestamps (for rate-stats dashboard)
# threading.Lock is a factory function, not a class — capture the actual type once
# so isinstance() checks in _run_security_checks() work correctly.
_THREADING_LOCK_TYPE = type(_rl_lock)

# ── EXTERNAL API CALL COUNTERS ──
_ext_lock  = threading.Lock()
# Timestamp lists; filtered to last 24 h for "today" stats, last 1 h for rate-stats.
_ext_calls: dict = {'api': [], 'dexscreener': [], 'jupiter': []}


def _ext_hit(category: str) -> None:
    """Record one external or internal API call for admin observability."""
    now = time.time()
    with _ext_lock:
        lst = _ext_calls.get(category)
        if lst is not None:
            lst.append(now)

def _rate_ok(key: str, limit: int, window: int) -> bool:
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl_hits.get(key, []) if now - t < window]
        if len(hits) >= limit:
            _rl_hits[key] = hits
            return False
        hits.append(now)
        _rl_hits[key] = hits
        return True

def _record_block(key: str) -> None:
    """Record that a rate-limit block occurred for this key (for admin observability)."""
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl_blocked.get(key, []) if now - t < 3600]
        hits.append(now)
        _rl_blocked[key] = hits

def rate_limit(limit: int, window: int = 60, ban: bool = False):
    """Sliding-window rate limiter.  When ban=True, repeated overages trigger the
    IP-ban system (_record_ip_failure) in addition to returning 429.
    The owner wallet is always bypassed — session.get('wallet') is checked
    so this works for every endpoint without any per-route special-casing."""
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            ip  = request.remote_addr or '0.0.0.0'
            # Owner IP and owner wallet are never rate-limited or banned
            if ip in _OWNER_IPS or _is_owner(session.get('wallet', '')):
                return f(*args, **kwargs)
            # Respect existing bans before even counting the request
            if ban and _is_banned(ip):
                return jsonify({'ok': False, 'msg': 'Too many requests — slow down'}), 429
            key = f.__name__ + ':' + ip
            if not _rate_ok(key, limit, window):
                _record_block(key)
                if ban:
                    # Only ban for extreme volume — 100+ req/min on this endpoint
                    _now = time.time()
                    with _rl_lock:
                        _recent = len([t for t in _rl_hits.get(key, []) if _now - t < 60])
                    if _recent >= 100:
                        _record_ip_failure(ip)
                return jsonify({'ok': False, 'msg': 'Too many requests — slow down'}), 429
            return f(*args, **kwargs)
        return wrapped
    return decorator

# ── MEMORY CLEANUP ──
_USER_STATES_MAX = 200   # evict LRU entries beyond this cap

def _cleanup_loop():
    """Periodically evict stale rate-limit buckets, idle user states, and dead position slots."""
    while True:
        time.sleep(300)
        now = time.time()
        # Evict expired rate-limit buckets and block records
        with _rl_lock:
            stale = [k for k, hits in _rl_hits.items() if not any(now - t < 120 for t in hits)]
            for k in stale:
                del _rl_hits[k]
            stale_b = [k for k, hits in _rl_blocked.items() if not any(now - t < 3600 for t in hits)]
            for k in stale_b:
                del _rl_blocked[k]
        # Trim external-call lists to last 25 h (keeps "today" window fresh)
        _cutoff_ext = now - 90000
        with _ext_lock:
            for cat in list(_ext_calls.keys()):
                _ext_calls[cat] = [t for t in _ext_calls[cat] if t > _cutoff_ext]
        # Evict expired IP bans and stale warn records
        for ip in list(_ip_ban.keys()):
            if now >= _ip_ban[ip]:
                _ip_ban.pop(ip, None)
                _ip_warn.pop(ip, None)
        # Evict stale AI cache entries (keep only entries younger than 2× TTL)
        ai_cutoff = now - _AI_CACHE_TTL * 2
        for mint in list(_ai_cache.keys()):
            if _ai_cache[mint].get('ts', 0) < ai_cutoff:
                del _ai_cache[mint]
        # Prune zero-amount position slots that accumulate in active traders
        for us in list(user_states.values()):
            pos = us.get('positions')
            if pos and len(pos) > 200:
                dead = [m for m, p in list(pos.items()) if not p.get('amount')]
                for m in dead[:len(pos) - 100]:
                    pos.pop(m, None)
        # Evict idle user states beyond cap
        if len(user_states) > _USER_STATES_MAX:
            by_age = sorted(
                user_states.items(),
                key=lambda kv: kv[1].get('balance_fetched_at', 0),
            )
            for wallet, _ in by_age[:len(user_states) - _USER_STATES_MAX]:
                try:
                    _ws = user_states[wallet]
                    _has_open_pos = any(p.get('amount', 0) > 0 for p in _ws.get('positions', {}).values())
                    # Never evict a wallet with a running bot or an open position — hydration
                    # would rebuild a SECOND, separate positions dict for it on next touch,
                    # diverging from whatever the still-running bot thread holds a reference to.
                    if not _ws.get('trader_running') and not _has_open_pos:
                        del user_states[wallet]
                except KeyError:
                    pass  # already removed by another thread

# ── SYSTEM AUDIT ──
_audit_state: dict = {
    'status': 'unknown',   # 'pass' | 'warn' | 'fail' | 'unknown'
    'checks': [],
    'ran_at': None,
    'ran_at_ts': 0.0,
}

def _run_audit() -> dict:
    checks = []

    # 1. Database connectivity
    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            c = conn.cursor()
            c.execute('SELECT COUNT(*) FROM users')
            n_users = c.fetchone()[0]
            c.execute('SELECT COUNT(*) FROM trades')
            n_trades = c.fetchone()[0]
        finally:
            conn.close()
        checks.append({'name': 'Database', 'status': 'pass',
                        'msg': f'{n_users} user(s), {n_trades} trade(s) on record'})
    except Exception as e:
        checks.append({'name': 'Database', 'status': 'fail', 'msg': str(e)[:80]})

    # 2. Token feed freshness
    n_tokens = len(state.get('tokens', []))
    if n_tokens == 0:
        checks.append({'name': 'Token Feed', 'status': 'warn',
                        'msg': 'No tokens loaded — DexScreener scan pending or h1≥50% filter active'})
    elif n_tokens < 3:
        checks.append({'name': 'Token Feed', 'status': 'warn',
                        'msg': f'Only {n_tokens} token(s) visible — market filter is very strict right now'})
    else:
        checks.append({'name': 'Token Feed', 'status': 'pass',
                        'msg': f'{n_tokens} trending token(s) loaded'})

    # 3. Solana RPC
    try:
        r = requests.post(SOLANA_RPC,
                          json={'jsonrpc': '2.0', 'id': 1, 'method': 'getHealth'},
                          timeout=5)
        health = r.json().get('result', '')
        if health == 'ok':
            checks.append({'name': 'Solana RPC', 'status': 'pass', 'msg': 'Mainnet RPC healthy'})
        else:
            checks.append({'name': 'Solana RPC', 'status': 'warn',
                            'msg': f'RPC returned: {str(health)[:40]}'})
    except Exception as e:
        checks.append({'name': 'Solana RPC', 'status': 'fail',
                        'msg': f'Unreachable — {str(e)[:60]}'})

    # 4. DexScreener API (token discovery source)
    if time.time() < _dex_429_until:
        remaining = int(_dex_429_until - time.time())
        checks.append({'name': 'DexScreener', 'status': 'warn',
                        'msg': f'Rate-limited (429) — backoff {remaining}s remaining'})
    else:
        try:
            r = requests.get(
                'https://api.dexscreener.com/latest/dex/tokens/' + USDC_MINT,
                headers=_DEX_HEADERS, timeout=6)
            if r.status_code == 200:
                checks.append({'name': 'DexScreener', 'status': 'pass',
                                'msg': f'HTTP {r.status_code} — token data available'})
            else:
                checks.append({'name': 'DexScreener', 'status': 'warn',
                                'msg': f'HTTP {r.status_code} — degraded'})
        except Exception as e:
            checks.append({'name': 'DexScreener', 'status': 'fail',
                            'msg': f'Unreachable — {str(e)[:60]}'})

    # 5. Jupiter API (swap quote endpoint — critical for trade execution)
    _sol_mint    = 'So11111111111111111111111111111111111111112'
    _jup_url     = (JUPITER_PROXY + '/quote') if JUPITER_PROXY else 'https://api.jup.ag/swap/v1/quote'
    _jup_headers = {'Accept': 'application/json', 'User-Agent': 'Mozilla/5.0 OrcAgent/1.0'}
    if PROXY_SECRET:
        _jup_headers['X-Proxy-Secret'] = PROXY_SECRET
    _route_label = f'via proxy ({JUPITER_PROXY})' if JUPITER_PROXY else 'direct (quote-api.jup.ag)'
    try:
        jr = requests.get(
            _jup_url,
            params={
                'inputMint':   USDC_MINT,
                'outputMint':  _sol_mint,
                'amount':      '1000000',
                'slippageBps': '300',
            },
            headers=_jup_headers,
            timeout=8,
        )
        if jr.status_code == 200:
            checks.append({'name': 'Jupiter API', 'status': 'pass',
                            'msg': f'Reachable {_route_label} — HTTP 200, quote OK'})
        elif jr.status_code == 429:
            checks.append({'name': 'Jupiter API', 'status': 'warn',
                            'msg': f'Rate-limited (429) {_route_label}'})
        else:
            checks.append({'name': 'Jupiter API', 'status': 'warn',
                            'msg': f'HTTP {jr.status_code} {_route_label} — {jr.text[:80]}'})
    except Exception as e:
        checks.append({'name': 'Jupiter API', 'status': 'fail',
                        'msg': f'Unreachable {_route_label} — {str(e)[:80]}'})

    # 5b. Anthropic API (AI signals + narrative agent -- credit balance / auth).
    # A rejected request (400/401) costs nothing -- Anthropic validates
    # (including balance) before any generation happens, so this is safe to
    # run on the same 5-minute cycle as the other checks with no real cost.
    if not ANTHROPIC_API_KEY:
        checks.append({'name': 'Anthropic API', 'status': 'warn',
                        'msg': 'ANTHROPIC_API_KEY not configured — AI signals/narrative agent disabled'})
    else:
        try:
            ar = requests.post(
                _ANTHROPIC_URL,
                headers={**_ANTHROPIC_HEADERS, 'x-api-key': ANTHROPIC_API_KEY},
                json={'model': 'claude-haiku-4-5', 'max_tokens': 1,
                      'messages': [{'role': 'user', 'content': 'hi'}]},
                timeout=8,
            )
            if ar.status_code == 200:
                checks.append({'name': 'Anthropic API', 'status': 'pass', 'msg': 'Reachable — HTTP 200'})
            elif ar.status_code == 400 and 'credit balance' in ar.text.lower():
                checks.append({'name': 'Anthropic API', 'status': 'fail',
                                'msg': 'Credit balance too low — AI signals/narrative agent failing closed'})
            elif ar.status_code == 401:
                checks.append({'name': 'Anthropic API', 'status': 'fail', 'msg': 'Invalid API key (401)'})
            elif ar.status_code == 429:
                checks.append({'name': 'Anthropic API', 'status': 'warn', 'msg': 'Rate-limited (429)'})
            else:
                checks.append({'name': 'Anthropic API', 'status': 'warn',
                                'msg': f'HTTP {ar.status_code} — {ar.text[:80]}'})
        except Exception as e:
            checks.append({'name': 'Anthropic API', 'status': 'fail',
                            'msg': f'Unreachable — {str(e)[:60]}'})

    # 6. Encryption key (private key storage)
    if _fernet is not None:
        checks.append({'name': 'Encryption Key', 'status': 'pass',
                        'msg': 'Fernet key initialised — private keys stored securely'})
    else:
        checks.append({'name': 'Encryption Key', 'status': 'fail',
                        'msg': 'Fernet not initialised — cannot save private keys'})

    # 7. Memory
    n_states = len(user_states)
    n_rl     = len(_rl_hits)
    if n_states > 190:
        checks.append({'name': 'Memory', 'status': 'fail',
                        'msg': f'{n_states} user states (cleanup loop may be stuck)'})
    elif n_states > 150:
        checks.append({'name': 'Memory', 'status': 'warn',
                        'msg': f'{n_states} user states in memory — approaching cap'})
    else:
        checks.append({'name': 'Memory', 'status': 'pass',
                        'msg': f'{n_states} user state(s), {n_rl} rate-limit bucket(s)'})

    # 8. Active traders
    active = sum(1 for us in list(user_states.values()) if us.get('trader_running'))
    checks.append({'name': 'Active Traders', 'status': 'pass',
                    'msg': f'{active} trader(s) currently running'})

    # Overall
    if any(c['status'] == 'fail' for c in checks):
        overall = 'fail'
    elif any(c['status'] == 'warn' for c in checks):
        overall = 'warn'
    else:
        overall = 'pass'

    return {
        'status':    overall,
        'checks':    checks,
        'ran_at':    datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
        'ran_at_ts': time.time(),
    }

def _audit_loop():
    time.sleep(15)   # let token/TOTD loops start first
    while True:
        try:
            result = _run_audit()
            _audit_state.update(result)
        except Exception as e:
            _audit_state.update({
                'status':    'fail',
                'checks':    [{'name': 'Audit runner', 'status': 'fail', 'msg': str(e)[:120]}],
                'ran_at':    datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'),
                'ran_at_ts': time.time(),
            })
        time.sleep(300)   # re-run every 5 minutes

# ── TRADER LOCK (prevents double-start race condition) ──
_trader_lock = threading.Lock()
# Guards the check-hydrate-insert sequence in get_user_state() so a wallet's
# open positions are only ever loaded from the DB once per process lifetime.
_user_states_lock = threading.Lock()

# ── SQLITE DATABASE ──
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # WAL mode is stored in the database file itself, so setting it once here
    # at startup is enough -- every one of the ~280 other sqlite3.connect(DB_FILE)
    # call sites across the app then opens the DB already in WAL mode. This lets
    # readers and writers run concurrently instead of blocking each other, which
    # matters a lot with only 1 gunicorn worker / 4 threads serving requests
    # while the bot loop and monitor also hit the same file.
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA busy_timeout=5000')
    # Migrate old X-based schema if it exists
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
    if c.fetchone():
        c.execute('PRAGMA table_info(users)')
        cols = [row[1] for row in c.fetchall()]
        if 'x_username' in cols:
            c.execute('DROP TABLE users')
            conn.commit()
    c.execute('CREATE TABLE IF NOT EXISTS server_config (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id                       INTEGER PRIMARY KEY AUTOINCREMENT,
        wallet_address           TEXT UNIQUE NOT NULL,
        encrypted_private_key    TEXT DEFAULT '',
        trading_active           INTEGER DEFAULT 0,
        max_trade_size           REAL DEFAULT 10.0,
        min_trade_size           REAL DEFAULT 1.0,
        daily_loss_limit         REAL DEFAULT 50.0,
        trade_size_unit_migrated INTEGER DEFAULT 1,
        created_at               TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    # Defensive backstop: CREATE TABLE IF NOT EXISTS above is a no-op against a
    # users table that already exists on disk from an older schema version, so
    # the inline UNIQUE constraint on wallet_address is not guaranteed to have
    # ever actually been applied to a production DB that predates it. Without
    # this, a check-then-insert race (see save_settings()) can silently create
    # two rows for the same wallet_address, and every SELECT id FROM users
    # WHERE wallet_address=? in the app would then resolve to whichever
    # duplicate happens to match first -- splitting one account's trade
    # history across two user_id values.
    c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_wallet_address ON users(wallet_address)')
    c.execute('''CREATE TABLE IF NOT EXISTS trades (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      INTEGER NOT NULL,
        token        TEXT,
        entry_price  REAL,
        exit_price   REAL,
        amount       REAL,
        pnl          REAL,
        fee_amount   REAL DEFAULT 0,
        timestamp    TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS token_calls (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        wallet        TEXT NOT NULL,
        mint          TEXT NOT NULL,
        symbol        TEXT DEFAULT '',
        token_name    TEXT DEFAULT '',
        price_at_call REAL NOT NULL,
        mcap_at_call  REAL DEFAULT 0,
        peak_price    REAL NOT NULL,
        peak_at       TEXT DEFAULT CURRENT_TIMESTAMP,
        timestamp     TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_token_calls_mint ON token_calls(mint)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_token_calls_user_ts ON token_calls(user_id, timestamp)')
    c.execute('''CREATE TABLE IF NOT EXISTS call_likes (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER NOT NULL,
        call_id    INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, call_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (call_id) REFERENCES token_calls(id)
    )''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_call_likes_call ON call_likes(call_id)')
    c.execute('''CREATE TABLE IF NOT EXISTS fees (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_wallet  TEXT NOT NULL,
        token        TEXT,
        gross_profit REAL,
        fee_amount   REAL,
        fee_tx       TEXT DEFAULT '',
        timestamp    TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    # Open positions: persists what used to live only in user_states[wallet]['positions']
    # (RAM), so a process restart no longer silently loses track of held tokens. A row
    # exists iff the position is currently open — closing it means deleting the row.
    c.execute('''CREATE TABLE IF NOT EXISTS open_positions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         INTEGER NOT NULL,
        mint_address    TEXT NOT NULL,
        symbol          TEXT DEFAULT '',
        amount          REAL NOT NULL,
        buy_price       REAL NOT NULL,
        spend           REAL DEFAULT 0,
        entry_liquidity REAL DEFAULT 0,
        opened_at       REAL DEFAULT 0,
        source          TEXT DEFAULT 'bot',
        updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, mint_address),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    # Rug-risk signals captured at buy time (rugcheck.xyz + on-chain mint/freeze
    # authority — see _check_lp_locked()/_check_mint_safety()), carried through
    # open_positions so a restart doesn't lose them, then copied onto the closed
    # `trades` row so …212152 tokens truncated…rivate key. A BSC position must not reach it.
    positions = {k: v for k, v in us.get('positions', {}).items()
                 if v.get('amount', 0) > 0 and v.get('chain', 'solana') == 'solana'}
    if not positions:
        return jsonify({'ok': True, 'msg': 'No open positions to close'})
    closed, failed = 0, 0
    for mint, pos in list(positions.items()):
        try:
            with _use_key(enc_blob, target) as _pk:
                # '0' = sell the actual on-chain balance, not the tracked pos['amount']
                # -- they can drift, and this is a full close so no dust should remain.
                sell_ok = _execute_user_swap(target, _pk, 'sell', mint, '0')
            if sell_ok:
                _close_open_position(user_id, target, mint)
                closed += 1
            else:
                failed += 1
        except Exception as e:
            print(f'[admin] force-close-all sell error for {mint[:8]}: {e}', flush=True)
            failed += 1
    print(f'[admin] force-close-all {target[:8]}… closed={closed} failed={failed}', flush=True)
    return jsonify({'ok': True, 'msg': f'Closed {closed} position(s)' + (f', {failed} failed' if failed else '')})

@app.route('/api/admin/rate-stats')
@rate_limit(20, 60)
def admin_rate_stats():
    err = _require_role('admin', 'executive', 'analyst')
    if err: return err

    now        = time.time()
    hour_ago   = now - 3600
    # UTC midnight: floor to 86400 s boundary
    today_start = now - (now % 86400)

    with _ext_lock:
        api_today = sum(1 for t in _ext_calls['api']         if t >= today_start)
        jup_today = sum(1 for t in _ext_calls['jupiter']     if t >= today_start)
        dex_today = sum(1 for t in _ext_calls['dexscreener'] if t >= today_start)

    # Aggregate per-endpoint request and block counts for the last hour.
    # Keys in _rl_hits/blocked are "function_name:ip" or special forms like
    # "global:ip" and "withdraw_wallet:wallet" — split on the FIRST colon.
    ep_hits    = {}
    ep_blocked = {}
    with _rl_lock:
        for key, hits in _rl_hits.items():
            ep = key.split(':', 1)[0]
            ep_hits[ep] = ep_hits.get(ep, 0) + sum(1 for t in hits if t >= hour_ago)
        for key, hits in _rl_blocked.items():
            ep = key.split(':', 1)[0]
            ep_blocked[ep] = ep_blocked.get(ep, 0) + sum(1 for t in hits if t >= hour_ago)

    all_eps = set(ep_hits) | set(ep_blocked)
    endpoints = sorted(
        [{'endpoint': ep,
          'requests_1h': ep_hits.get(ep, 0),
          'blocked_1h':  ep_blocked.get(ep, 0)}
         for ep in all_eps if ep_hits.get(ep, 0) or ep_blocked.get(ep, 0)],
        key=lambda x: (-x['blocked_1h'], -x['requests_1h']),
    )

    return jsonify({
        'ok':                    True,
        'api_calls_today':       api_today,
        'jupiter_calls_today':   jup_today,
        'dexscreener_calls_today': dex_today,
        'endpoints':             endpoints,
    })


@app.route('/api/admin/backups')
@rate_limit(20, 60)
def admin_backups():
    _log_readonly_attempt()
    caller = _authenticated_wallet()
    if not caller or not _is_owner(caller):
        return jsonify({'error': 'Unauthorized'}), 403
    backups = []
    try:
        if os.path.isdir(BACKUP_DIR):
            for fname in sorted(os.listdir(BACKUP_DIR), reverse=True):
                if fname.startswith('orcagent_') and (fname.endswith('.db') or fname.endswith('.db.gz')):
                    fpath = os.path.join(BACKUP_DIR, fname)
                    stat  = os.stat(fpath)
                    date_str = fname.replace('orcagent_', '').replace('.db.gz', '').replace('.db', '')
                    backups.append({
                        'filename': fname,
                        'size':     stat.st_size,
                        'date':     date_str,
                    })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    return jsonify({'ok': True, 'backups': backups, 'backup_dir': BACKUP_DIR})

def _recover_uncollected_fees(triggered_by: str = 'manual') -> dict:
    """Send all unpaid fees (fee_paid=0) from each user's trading wallet to FEE_WALLET --
    applies to winning and losing trades alike, since the fee is a flat % of the swap
    amount, not of profit.
    Returns a summary dict. Safe to call from a background thread or an API endpoint."""
    # A gate, not the destination -- the fees themselves go to FEE_WALLET.
    # This only refuses to run the sweep on a platform with nobody
    # configured to own it.
    if not OWNER_WALLETS:
        print('[fee-recovery] no owner wallet configured — skipping', flush=True)
        return {'ok': False, 'error': 'No owner wallet configured', 'total_sol': 0.0, 'results': []}

    print(f'[fee-recovery] ── START ({triggered_by}) ──', flush=True)
    try:
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        # Group unpaid trades by user so we send one TX per user instead of one per trade.
        # Excludes trades closed in the last 2 minutes: _charge_txn_fee() spawns a
        # background thread per sell that waits 12s then attempts its own send_sol_fee
        # for that exact trade before marking it fee_paid -- without this window, a
        # recovery sweep (hourly, or triggered manually) landing during those ~12+
        # seconds would see the same still-fee_paid=0 trade and send a second, real
        # on-chain fee transfer for it. 2 minutes is comfortably longer than the 12s
        # delay plus realistic RPC/retry time for that thread to finish one way or
        # the other.
        c.execute('''
            SELECT u.wallet_address,
                   u.encrypted_private_key,
                   GROUP_CONCAT(t.id)              AS trade_ids,
                   COALESCE(SUM(t.fee_amount), 0)  AS total_fee
            FROM trades t
            JOIN users u ON u.id = t.user_id
            WHERE (t.fee_paid IS NULL OR t.fee_paid = 0)
              AND datetime(t.timestamp) < datetime('now', '-2 minutes')
              AND u.encrypted_private_key IS NOT NULL
              AND u.encrypted_private_key != ""
              -- A trade whose fee was already collected inside its own swap
              -- (bundled=True) but never got to flip trades.fee_paid=1 --
              -- e.g. the process restarted mid-write, back when that update
              -- ran on a background thread -- must NOT be recovered here.
              -- Doing so would send a second, real, separate SOL transfer
              -- for a fee the user already paid invisibly, which is exactly
              -- the "extra transaction" users have been reporting. A
              -- matching bundled `fees` row within 5 minutes of the trade's
              -- own timestamp is strong evidence it was already collected.
              AND NOT EXISTS (
                  SELECT 1 FROM fees f
                  WHERE f.user_wallet = u.wallet_address
                    AND f.kind = 'sell'
                    AND f.status = 'ok'
                    AND f.fee_tx = 'bundled-in-swap'
                    AND ABS(strftime('%s', f.timestamp) - strftime('%s', t.timestamp)) < 300
              )
            GROUP BY u.wallet_address, u.encrypted_private_key
        ''')
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        print(f'[fee-recovery] DB query failed: {e}', flush=True)
        return {'ok': False, 'error': str(e), 'total_sol': 0.0, 'results': []}

    if not rows:
        print('[fee-recovery] no unpaid trades found', flush=True)
        return {'ok': True, 'total_sol': 0.0, 'results': [], 'msg': 'No unpaid fees found'}

    total_recovered = 0.0
    results         = []

    for (user_wallet, enc_blob, trade_ids_str, total_fee_raw) in rows:
        total_fee = round(float(total_fee_raw or 0), 6)
        trade_ids = [int(x) for x in (trade_ids_str or '').split(',') if x.strip().isdigit()]
        sw = (user_wallet[:6] + '...' + user_wallet[-4:]) if len(user_wallet) >= 10 else user_wallet

        print(f'[fee-recovery] {sw}  unpaid_trades={len(trade_ids)}  '
              f'total_fee={total_fee:.6f} SOL', flush=True)

        if total_fee < 0.0001:
            print(f'[fee-recovery] {sw} below dust threshold — skipping', flush=True)
            results.append({'wallet': sw, 'fee': total_fee, 'status': 'skipped_dust'})
            continue

        try:
            # ── Decrypt key — failures are silenced here and NEVER forwarded to
            # any user-facing log or API response.  add_user_log is intentionally
            # not called; the error only appears in server stdout so the admin can
            # diagnose it without confusing the wallet owner.
            try:
                with _use_key(enc_blob, user_wallet) as pk:
                    from solders.keypair import Keypair as _KP_fr
                    signer = str(_KP_fr.from_base58_string(pk).pubkey())
                    signer_sol = _get_user_sol(signer)
                    if signer_sol < 0.001:
                        print(f'[fee-recovery] {sw} signer={signer[:6]}...{signer[-4:]} has '
                              f'{signer_sol:.6f} SOL (<0.001) — not enough to cover the network fee, '
                              f'skipping', flush=True)
                        results.append({'wallet': sw, 'fee': total_fee, 'trades': len(trade_ids),
                                        'status': 'skipped_low_balance', 'sol_balance': signer_sol})
                        continue

                    # Mark these trades fee_paid BEFORE sending -- send_sol_fee() below is an
                    # irreversible on-chain transfer, so this order guarantees the same trades
                    # can never be re-selected and sent a second time, even if the process
                    # crashes, the DB is briefly locked, or anything else fails between the
                    # transfer and recording it. The downside -- a send that then fails leaves
                    # these trades marked paid without the fee actually collected -- is a
                    # recoverable, admin-visible under-collection, not a user-harming double
                    # charge (which is what the old post-send ordering risked).
                    conn2 = sqlite3.connect(DB_FILE)
                    conn2.execute('PRAGMA busy_timeout=3000')
                    placeholders = ','.join('?' * len(trade_ids))
                    conn2.execute(
                        f'UPDATE trades SET fee_paid=1 WHERE id IN ({placeholders})',
                        trade_ids)
                    conn2.commit()
                    conn2.close()

                    tx_sig = send_sol_fee(pk, FEE_WALLET, total_fee)
            except InvalidToken:
                # Wrong ENCRYPTION_KEY for this wallet, or the stored blob is corrupted.
                # decrypt_private_key() already printed the detailed reason with wallet + fingerprint.
                # Skip silently — do NOT call add_user_log, no frontend notification sent.
                print(f'[fee-recovery] {sw} full_wallet={user_wallet} SKIP — key decryption '
                      f'failed (InvalidToken, enc_key_fp={_enc_key_fingerprint}). '
                      f'User must re-save their trading key in Settings. '
                      f'This error is NOT forwarded to the user UI.', flush=True)
                results.append({'wallet': sw, 'fee': total_fee, 'trades': len(trade_ids),
                                'status': 'skipped_decrypt_error'})
                continue

            # Record the successful send in the fees table for reporting/audit. Trades are
            # already marked paid above, so a failure here can't cause a double-send on the
            # next recovery run -- worst case is just a missing audit row for a real transfer.
            conn2 = sqlite3.connect(DB_FILE)
            conn2.execute('PRAGMA busy_timeout=3000')
            conn2.execute(
                '''INSERT INTO fees (user_wallet, token, gross_profit, fee_amount, fee_tx, status)
                   VALUES (?,?,?,?,?,?)''',
                (user_wallet, '[recovery]', total_fee / _get_fee_rate(), total_fee, tx_sig, 'ok'))
            # Referral payout (20% of the fee just actually collected) -- the normal
            # per-trade path (_charge_txn_fee/_do_fee) credits this on every successful
            # send, but a trade recovered here (its original attempt failed or never ran)
            # would otherwise never pay its referrer at all.
            try:
                ref_row = conn2.execute(
                    'SELECT referred_by FROM users WHERE wallet_address=?', (user_wallet,)).fetchone()
                if ref_row and ref_row[0]:
                    referrer = ref_row[0]
                    earned   = round(total_fee * 0.20, 6)
                    conn2.execute(
                        'INSERT INTO referral_earnings '
                        '(referrer_wallet, referred_wallet, trade_fee_sol, earned_sol) VALUES (?,?,?,?)',
                        (referrer, user_wallet, total_fee, earned))
                    conn2.execute(
                        'UPDATE users SET referral_balance = referral_balance + ? WHERE wallet_address=?',
                        (earned, referrer))
                    print(f'[referral] {sw} → referrer {referrer[:6]}... earns {earned:.6f} SOL '
                          f'(20% of {total_fee:.6f} SOL recovered fee)', flush=True)
            except Exception as ref_e:
                print(f'[referral] ✗ credit failed for {sw}: {ref_e}', flush=True)
            conn2.commit()
            conn2.close()

            total_recovered += total_fee
            print(f'[fee-recovery] ✓ {sw} sent {total_fee:.6f} SOL  TX:{tx_sig[:20]}...  '
                  f'{len(trade_ids)} trade(s) marked fee_paid=1', flush=True)
            add_log(f'[fee-recovery] {sw} recovered {total_fee:.5f} SOL  TX:{tx_sig[:14]}...')
            results.append({'wallet': sw, 'fee': total_fee, 'trades': len(trade_ids),
                            'tx': tx_sig, 'status': 'sent'})

        except Exception as e:
            # Covers send_sol_fee failure, DB errors, keypair derivation errors, etc.
            # Decrypt errors are handled by the inner except above and never reach here.
            # These trades may already be marked fee_paid=1 (set before send_sol_fee is
            # called, above) even though this branch was reached -- that's intentional,
            # see the comment at the UPDATE -- so this won't be retried next run even on
            # failure. Check the fees table for a matching row before assuming nothing
            # happened.
            err = _redact_keys(str(e)[:200])
            print(f'[fee-recovery] ✗ {sw} FAILED: {err}', flush=True)
            results.append({'wallet': sw, 'fee': total_fee, 'trades': len(trade_ids),
                            'error': err, 'status': 'failed'})

    print(f'[fee-recovery] ── DONE  total_recovered={total_recovered:.6f} SOL ──', flush=True)
    return {
        'ok':         True,
        'total_sol':  round(total_recovered, 6),
        'wallets':    len(rows),
        'results':    results,
    }


def _snapshot_portfolios(triggered_by: str = 'manual') -> dict:
    """Record each user's current total portfolio value (SOL balance +
    open positions, at current prices) into portfolio_snapshots -- the same
    USD-value calc as api_portfolio_summary() (regel ~11149-11192), just run
    for every user with a wallet on file instead of just the caller.
    get_user_state(wallet) hydrates positions from open_positions on first
    touch (see _hydrate_positions_from_db), so this reflects persisted
    positions correctly even for users this process hasn't touched yet.
    Safe to call from a background thread or an API endpoint."""
    print(f'[portfolio-snapshot] ── START ({triggered_by}) ──', flush=True)
    try:
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        c.execute("SELECT id, wallet_address FROM users WHERE wallet_address IS NOT NULL AND wallet_address != ''")
        rows = c.fetchall()
        conn.close()
    except Exception as e:
        print(f'[portfolio-snapshot] DB query failed: {e}', flush=True)
        return {'ok': False, 'error': str(e), 'saved': 0, 'total': 0}

    sol_price = _sol_price_usd
    live_map  = {t['mint']: t for t in state.get('tokens', [])}

    # Fetch every user's SOL balance concurrently (bounded) instead of one RPC
    # round-trip at a time -- at any real user count, doing this sequentially
    # (each getBalance call can take up to the 8s timeout) made this hourly
    # job's runtime grow linearly with the user base. Only the RPC call itself
    # runs in parallel; get_user_state()/DB writes below stay single-threaded
    # per wallet, so there's no shared-state concurrency to worry about here.
    _balances = {}
    _bal_lock = threading.Lock()
    _sem      = threading.Semaphore(10)

    def _fetch_balance(user_id, wallet):
        with _sem:
            try:
                r = requests.post(SOLANA_RPC, json={
                    'jsonrpc': '2.0', 'id': 1, 'method': 'getBalance', 'params': [wallet]
                }, timeout=8)
                sol_balance = r.json()['result']['value'] / 1e9
                with _bal_lock:
                    _balances[user_id] = (wallet, sol_balance, None)
            except Exception as e:
                with _bal_lock:
                    _balances[user_id] = (wallet, None, e)

    _threads = [threading.Thread(target=_fetch_balance, args=(uid, w)) for uid, w in rows]
    for _t in _threads: _t.start()
    for _t in _threads: _t.join()

    saved = 0
    conn2 = sqlite3.connect(DB_FILE)
    try:
        for user_id, wallet in rows:
            _wallet, sol_balance, err = _balances.get(user_id, (wallet, None, 'no result'))
            if err is not None:
                print(f'[portfolio-snapshot] user_id={user_id} FAILED: {err}', flush=True)
                continue
            try:
                us = get_user_state(wallet)
                total_value_usd = sol_balance * sol_price if sol_price else 0.0
                for mint, pos in us.get('positions', {}).items():
                    if pos.get('amount', 0) <= 0 or pos.get('buy_price', 0) <= 0:
                        continue
                    amount    = float(pos.get('amount', 0))
                    live      = live_map.get(mint)
                    cur_price = float(live.get('price', 0) or 0) if live else 0.0
                    if not live:
                        td        = get_token_data(mint)
                        cur_price = float(td['price']) if td else 0.0
                    if cur_price > 0:
                        total_value_usd += amount * cur_price

                conn2.execute(
                    'INSERT INTO portfolio_snapshots (user_id, total_value_usd) VALUES (?, ?)',
                    (user_id, round(total_value_usd, 4)))
                saved += 1
            except Exception as e:
                print(f'[portfolio-snapshot] user_id={user_id} FAILED: {e}', flush=True)
        conn2.commit()
    finally:
        conn2.close()

    print(f'[portfolio-snapshot] ── DONE  saved={saved}/{len(rows)} ──', flush=True)
    return {'ok': True, 'saved': saved, 'total': len(rows)}


@app.route('/api/admin/recover-fees', methods=['POST'])
@rate_limit(5, 60)
def admin_recover_fees():
    """Collect all unpaid fees (trades.fee_paid=0) and send them to OWNER_WALLET in one TX per user."""
    _log_readonly_attempt()
    wallet = _authenticated_wallet()
    if not wallet or not _is_owner(wallet):
        return _owner_denied(wallet, 'Recovering fees')
    result = _recover_uncollected_fees(triggered_by='admin-button')
    status = 200 if result.get('ok') else 500
    return jsonify(result), status



@app.route('/api/admin/tokens')
@rate_limit(20, 60)
def admin_tokens():
    _log_readonly_attempt()
    wallet = _authenticated_wallet()
    if not wallet or not _is_owner(wallet):
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        c.execute('''SELECT token,
                            COUNT(*) trades,
                            COALESCE(SUM(pnl),0) total_pnl,
                            COALESCE(AVG(pnl),0) avg_pnl,
                            COALESCE(MAX(pnl),0) best_pnl,
                            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) wins
                     FROM trades WHERE token IS NOT NULL AND token != ''
                     GROUP BY token ORDER BY trades DESC LIMIT 30''')
        tokens = []
        for r in c.fetchall():
            trades = int(r[1])
            wins   = int(r[5])
            tokens.append({
                'token':     r[0],
                'trades':    trades,
                'total_pnl': round(r[2], 4),
                'avg_pnl':   round(r[3], 4),
                'best_pnl':  round(r[4], 4),
                'win_rate':  round(wins / trades * 100, 0) if trades > 0 else 0,
            })
        conn.close()
        return jsonify({'tokens': tokens})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/health')
@rate_limit(20, 60)
def admin_health():
    # 'executive' was missing here even though every other endpoint the admin
    # dashboard's System tab calls (rate-stats, bans, the base /api/admin
    # summary) already allows it -- left this tab partly broken for that role.
    err = _require_role('admin', 'executive', 'moderator', 'analyst')
    if err: return err
    try:
        db_size_kb = 0
        try:
            db_size_kb = round(os.path.getsize(DB_FILE) / 1024, 1)
        except Exception:
            pass
        active_traders = sum(1 for us in user_states.values() if us.get('trader_running'))
        conn = sqlite3.connect(DB_FILE)
        c    = conn.cursor()
        c.execute('SELECT COUNT(*) FROM users')
        total_users = int(c.fetchone()[0] or 0)
        c.execute('SELECT COUNT(*) FROM users WHERE narrative_agent_enabled=1')
        narrative_agent_users = int(c.fetchone()[0] or 0)
        c.execute('SELECT COUNT(*) FROM security_log WHERE timestamp >= datetime("now", "-1 hour")')
        sec_events_1h = int(c.fetchone()[0] or 0)
        conn.close()
        with _dex_lock:
            dex_limited = time.time() < _dex_429_until

        # Real reachability/billing check, not just presence -- a rejected
        # request costs nothing (Anthropic validates, including balance,
        # before any generation happens), and this endpoint is only called
        # on-demand (System tab load), not polled, so this is safe to run
        # every time. Same check as _run_audit()'s "Anthropic API" entry.
        anthropic_status = 'missing'
        if ANTHROPIC_API_KEY:
            try:
                ar = requests.post(
                    _ANTHROPIC_URL,
                    headers={**_ANTHROPIC_HEADERS, 'x-api-key': ANTHROPIC_API_KEY},
                    json={'model': 'claude-haiku-4-5', 'max_tokens': 1,
                          'messages': [{'role': 'user', 'content': 'hi'}]},
                    timeout=8,
                )
                if ar.status_code == 200:
                    anthropic_status = 'ok'
                elif ar.status_code == 400 and 'credit balance' in ar.text.lower():
                    anthropic_status = 'no_credit'
                elif ar.status_code == 401:
                    anthropic_status = 'invalid_key'
                elif ar.status_code == 429:
                    anthropic_status = 'rate_limited'
                else:
                    anthropic_status = f'http_{ar.status_code}'
            except Exception:
                anthropic_status = 'unreachable'

        return jsonify({
            'tokens_tracked':   len(state.get('tokens', [])),
            'active_traders':   active_traders,
            'total_sessions':   len(user_states),
            'total_users':      total_users,
            'narrative_agent_users': narrative_agent_users,
            'db_size_kb':       db_size_kb,
            'ai_cache_size':    len(_ai_cache),
            'ai_disabled':      time.time() < _ai_disabled_until,
            'dex_rate_limited': dex_limited,
            'sec_events_1h':    sec_events_1h,
            'owner_configured': bool(OWNER_WALLETS),
            'jupiter_proxy':    bool(JUPITER_PROXY),
            'anthropic_key':    bool(ANTHROPIC_API_KEY),
            'anthropic_status': anthropic_status,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/bans')
@rate_limit(20, 60)
def admin_bans():
    """Return currently active IP bans and total rate-limit bucket count."""
    err = _require_role('admin', 'executive', 'moderator', 'analyst')
    if err: return err
    wallet = _current_wallet()
    now  = time.time()
    bans = []
    for ip, expires in list(_ip_ban.items()):
        if expires > now:
            bans.append({
                'ip':         ip,
                'expires_at': int(expires),
                'mins_left':  round((expires - now) / 60, 1),
                'permanent':  False,
            })
        else:
            _ip_ban.pop(ip, None)
            _ip_warn.pop(ip, None)
    with _rl_lock:
        rl_bucket_count = len(_rl_hits)
    return jsonify({'bans': sorted(bans, key=lambda x: (not x['permanent'], x['mins_left'] or 0), reverse=True),
                    'rl_bucket_count': rl_bucket_count,
                    'whitelisted_ips': sorted(_OWNER_IPS) if _is_owner(wallet) else []})


@app.route('/api/admin/user/ban', methods=['POST'])
def admin_ban_user():
    err = _require_role('admin', 'executive', 'moderator')
    if err: return err
    data   = request.get_json(silent=True) or {}
    target = data.get('wallet', '').strip()
    if not target:
        return jsonify({'ok': False, 'msg': 'Missing wallet'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute('DELETE FROM users WHERE wallet_address=?', (target,))
        conn.execute('DELETE FROM feed_posts WHERE wallet=?', (target,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@app.route('/api/admin/user/verify', methods=['POST'])
def admin_toggle_verify():
    body = request.get_json(silent=True) or {}
    target = body.get('wallet', '').strip()
    verified = bool(body.get('verified', True))
    err = _require_role('admin', 'executive', 'moderator') if verified else _require_role('admin', 'executive')
    if err: return err
    if not target:
        return jsonify({'ok': False, 'msg': 'Missing wallet'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute('UPDATE users SET is_verified=? WHERE wallet_address=?', (1 if verified else 0, target))
        conn.commit()
        _log_security_event('user_verified' if verified else 'user_unverified',
                             session.get('wallet', ''), f'target={target[:8]}...')
        return jsonify({'ok': True, 'verified': verified})
    finally:
        conn.close()

@app.route('/api/admin/ban', methods=['POST'])
def admin_ban_v2():
    err = _require_role('admin', 'executive', 'moderator')
    if err: return err
    target = (request.get_json(silent=True) or {}).get('wallet', '').strip()
    if not target:
        return jsonify({'ok': False, 'msg': 'Missing wallet'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute('DELETE FROM users WHERE wallet_address=?', (target,))
        conn.execute('DELETE FROM feed_posts WHERE wallet=?', (target,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@app.route('/api/admin/post/delete', methods=['POST'])
@csrf_exempt
def admin_delete_post():
    err = _require_role('admin', 'executive', 'moderator')
    if err: return err
    post_id = (request.get_json(silent=True) or {}).get('post_id')
    if not post_id:
        return jsonify({'ok': False, 'msg': 'Missing post_id'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        row = conn.execute('SELECT id FROM feed_posts WHERE id=?', (post_id,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'msg': 'Post not found'}), 404
        conn.execute('DELETE FROM feed_posts WHERE id=?', (post_id,))
        conn.commit()
        return jsonify({'ok': True})
    finally:
        conn.close()


@app.route('/api/admin/trades')
@rate_limit(20, 60)
def admin_trades():
    err = _require_role('admin', 'executive', 'moderator', 'analyst')
    if err: return err
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            SELECT t.id, u.wallet_address, t.token, t.entry_price, t.exit_price,
                   t.amount, t.pnl, t.fee_amount, t.timestamp
            FROM trades t
            LEFT JOIN users u ON t.user_id = u.id
            ORDER BY t.timestamp DESC LIMIT 200
        ''')
        rows = c.fetchall()
        conn.close()
        trades = []
        for r in rows:
            w = r[1] or ''
            trades.append({
                'id':          r[0],
                'wallet':      (w[:4] + '…' + w[-4:]) if len(w) >= 8 else w,
                'wallet_full': w,
                'token':       r[2] or '—',
                'entry':       round(r[3] or 0, 6),
                'exit':        round(r[4] or 0, 6),
                'amount':      round(r[5] or 0, 4),
                'pnl':         round(r[6] or 0, 4),
                'fee':         round(r[7] or 0, 4),
                'ts':          (r[8] or '')[:16],
            })
        return jsonify({'ok': True, 'trades': trades, 'total': len(trades)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/admin/posts')
@rate_limit(20, 60)
def admin_posts():
    err = _require_role('admin', 'executive', 'moderator', 'analyst')
    if err: return err
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''
            SELECT fp.id, fp.wallet, fp.content, fp.created_at, u.username
            FROM feed_posts fp
            LEFT JOIN users u ON fp.wallet = u.wallet_address
            ORDER BY fp.created_at DESC LIMIT 100
        ''')
        rows = c.fetchall()
        conn.close()
        posts = []
        for r in rows:
            w = r[1] or ''
            posts.append({
                'id':      r[0],
                'wallet':  (w[:4] + '…' + w[-4:]) if len(w) >= 8 else w,
                'wallet_full': w,
                'content': r[2] or '',
                'ts':      (r[3] or '')[:16],
                'author':  r[4] or ((w[:6] + '…' + w[-4:]) if len(w) >= 10 else w),
            })
        return jsonify({'ok': True, 'posts': posts, 'total': len(posts)})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/admin/revenue')
@rate_limit(20, 60)
def admin_revenue():
    err = _require_role('admin', 'executive', 'moderator', 'analyst')
    if err: return err
    today = datetime.datetime.utcnow().strftime('%Y-%m-%d')
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        ok_f = "(status IS NULL OR status='ok') AND (fee_tx IS NULL OR fee_tx NOT LIKE 'FAILED:%')"
        c.execute(f'SELECT COALESCE(SUM(fee_amount),0) FROM fees WHERE {ok_f}')
        collected = round(float(c.fetchone()[0] or 0), 4)
        c.execute(f'SELECT COALESCE(SUM(fee_amount),0) FROM fees WHERE {ok_f} AND timestamp LIKE ?', (today + '%',))
        today_sol = round(float(c.fetchone()[0] or 0), 4)
        c.execute('SELECT COALESCE(SUM(fee_amount),0) FROM fees WHERE status="failed" OR fee_tx LIKE "FAILED:%"')
        failed = round(float(c.fetchone()[0] or 0), 4)
        c.execute('''SELECT COALESCE(SUM(t.pnl * 0.05), 0) FROM trades t
                     WHERE t.pnl > 0 AND (t.fee_paid IS NULL OR t.fee_paid = 0)''')
        pending = round(float(c.fetchone()[0] or 0), 4)
        c.execute('''SELECT user_wallet, token, gross_profit, fee_amount, fee_tx, timestamp, status
                     FROM fees ORDER BY timestamp DESC LIMIT 200''')
        txs = []
        for r in c.fetchall():
            w = r[0] or ''
            status = r[6] or ('failed' if str(r[4] or '').startswith('FAILED:') else 'ok')
            txs.append({
                'wallet': (w[:4] + '…' + w[-4:]) if len(w) >= 8 else w,
                'token':  r[1], 'gross': round(r[2] or 0, 4),
                'fee':    round(r[3] or 0, 4), 'tx': r[4],
                'ts':     (r[5] or '')[:16], 'status': status,
            })
        conn.close()
        return jsonify({
            'ok': True,
            'collected': collected, 'today': today_sol,
            'failed': failed, 'pending': pending,
            'transactions': txs,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/admin/settings/get')
def admin_settings_get():
    err = _require_role('admin', 'executive', 'moderator', 'analyst')
    if err: return err
    conn = sqlite3.connect(DB_FILE)
    try:
        rows = dict(conn.execute("SELECT key, value FROM platform_settings").fetchall())
    finally:
        conn.close()
    return jsonify({
        'ok': True,
        'fee':           round(float(rows.get('fee_rate', FEE_RATE_DEFAULT)) * 100, 4),
        'max_positions': float(rows.get('max_positions_per_user', 5)),
        'min_deposit':   float(rows.get('min_deposit', 0.1)),
        'rate_limit':    int(float(rows.get('rate_limit', 20))),
    })


@app.route('/api/admin/settings/save', methods=['POST'])
@csrf_exempt
def admin_settings_save():
    err = _require_role('admin', 'executive')
    if err: return err
    wallet = session.get('wallet', '')
    data = request.get_json(silent=True) or {}
    max_positions = data.get('max_positions')
    min_deposit   = data.get('min_deposit')
    rate_limit_v  = data.get('rate_limit')
    saved = {}
    conn = sqlite3.connect(DB_FILE)
    try:
        if max_positions is not None:
            conn.execute(
                "INSERT INTO platform_settings (key, value) VALUES ('max_positions_per_user', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(float(max_positions)),)
            )
            saved['max_positions'] = float(max_positions)
        if min_deposit is not None:
            conn.execute(
                "INSERT INTO platform_settings (key, value) VALUES ('min_deposit', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(float(min_deposit)),)
            )
            saved['min_deposit'] = float(min_deposit)
        if rate_limit_v is not None:
            conn.execute(
                "INSERT INTO platform_settings (key, value) VALUES ('rate_limit', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(int(rate_limit_v)),)
            )
            saved['rate_limit'] = int(rate_limit_v)
        conn.commit()
    finally:
        conn.close()
    print(f'[admin] settings saved by {wallet[:8]}… → {saved}', flush=True)
    return jsonify({'ok': True, 'saved': saved})


@app.route('/api/admin/features/toggle', methods=['POST'])
@csrf_exempt
def admin_features_toggle():
    wallet = _authenticated_wallet()
    if not wallet or not hmac.compare_digest(wallet.encode(), ADMIN_WALLET.encode()):
        return jsonify({'ok': False, 'msg': 'Forbidden'}), 403
    data    = request.get_json(silent=True) or {}
    feature = str(data.get('feature', '')).strip()
    value   = bool(data.get('value', False))
    if not feature:
        return jsonify({'ok': False, 'msg': 'Missing feature'}), 400
    if not hasattr(admin_features_toggle, '_store'):
        admin_features_toggle._store = {}
    admin_features_toggle._store[feature] = value
    print(f'[admin] feature "{feature}" → {value} by {wallet[:8]}…', flush=True)
    return jsonify({'ok': True, 'feature': feature, 'value': value})


@app.route('/api/admin/whoami')
@csrf_exempt
def admin_whoami():
    wallet = _authenticated_wallet()
    if not wallet:
        return jsonify({'ok': False, 'msg': 'Not authenticated'}), 401
    role = get_user_role(wallet)
    if role == 'user':
        return jsonify({'ok': False, 'msg': 'Forbidden'}), 403
    # Role admits you to the page; being the OWNER_WALLET is a separate,
    # stricter check that the money-moving actions on it use. The page needs
    # both so it can hide buttons it already knows would be refused.
    return jsonify({'ok': True, 'wallet': wallet, 'role': role,
                    'is_owner': _is_owner(wallet), 'owner_configured': bool(OWNER_WALLETS)})


@app.route('/api/admin/roles', methods=['GET'])
@csrf_exempt
def admin_roles_list():
    wallet = _authenticated_wallet()
    if not wallet or not hmac.compare_digest(wallet.encode(), ADMIN_WALLET.encode()):
        return jsonify({'ok': False, 'msg': 'Forbidden'}), 403
    conn = sqlite3.connect(DB_FILE)
    try:
        rows = conn.execute(
            'SELECT wallet_address, role, invited_by, invited_at FROM admin_roles ORDER BY invited_at'
        ).fetchall()
        members = [{'wallet': r[0], 'role': r[1], 'invited_by': r[2], 'invited_at': (r[3] or '')[:10]}
                   for r in rows]
        # Always prepend the super-admin (owner) so they appear first
        owner = {'wallet': ADMIN_WALLET, 'role': 'Super-admin', 'invited_by': None, 'invited_at': ''}
        return jsonify({'ok': True, 'members': [owner] + members})
    finally:
        conn.close()


@app.route('/api/admin/invite', methods=['POST'])
@csrf_exempt
def admin_invite():
    err = _require_role('admin', 'executive')
    if err: return err
    admin_wallet = session.get('wallet', '')
    data        = request.get_json(silent=True) or {}
    invite_addr = str(data.get('wallet', '')).strip()
    role        = str(data.get('role', 'Moderator')).strip()
    if not is_valid_solana_address(invite_addr):
        return jsonify({'ok': False, 'msg': 'Invalid wallet address'}), 400
    if invite_addr == ADMIN_WALLET:
        return jsonify({'ok': False, 'msg': 'Owner wallet cannot be re-invited'}), 400
    if invite_addr == admin_wallet:
        return jsonify({'ok': False, 'msg': "You can't invite the wallet you're currently logged in with"}), 400
    if role not in ('Moderator', 'Analyst', 'Executive'):
        role = 'Moderator'
    # Granting Executive is owner-only, even though Executives themselves can invite
    # Moderator/Analyst -- otherwise a single Executive account (compromised, or just
    # a bad actor) could mint unlimited peer Executives, and only the owner can ever
    # remove a role (see admin_role_remove below), so this is the one place that gap
    # needs to be closed at grant time, not just at removal time.
    if role == 'Executive' and not hmac.compare_digest(admin_wallet.encode(), ADMIN_WALLET.encode()):
        return jsonify({'ok': False, 'msg': 'Only the owner can invite an Executive'}), 403
    conn = sqlite3.connect(DB_FILE)
    try:
        # Supersede any existing pending invite for this wallet
        conn.execute(
            "UPDATE admin_invites SET status='superseded' WHERE wallet=? AND status='pending'",
            (invite_addr,)
        )
        # Create fresh pending invite (user sees modal on next login)
        conn.execute(
            'INSERT INTO admin_invites(wallet, role, invited_by) VALUES(?,?,?)',
            (invite_addr, role, admin_wallet)
        )
        conn.commit()

        try:
            invited_uid = get_or_create_user(invite_addr)
            if invited_uid:
                notif_content = f'You were invited as {role} by {admin_wallet[:8]}…'
                _nc = sqlite3.connect(DB_FILE)
                _nc.execute(
                    'INSERT INTO notifications (user_id, type, content, link, actor_wallet) VALUES (?,?,?,?,?)',
                    (invited_uid, 'admin_invite', notif_content, '/', admin_wallet))
                _nc.commit()
                _send_push_notification(invited_uid, 'Admin invite', notif_content, '/')
                _nc.close()
        except Exception as _ne:
            print(f'[admin] invite notification failed: {_ne}', flush=True)

        print(f'[admin] invite queued {invite_addr[:8]}… as {role} by {admin_wallet[:8]}…', flush=True)
        return jsonify({
            'ok': True, 'wallet': invite_addr, 'role': role,
            'msg': 'Invite sent — user will see it when they log in',
        })
    finally:
        conn.close()


@app.route('/api/admin/invites')
@csrf_exempt
def admin_invites_pending():
    err = _require_role('admin', 'executive', 'moderator')
    if err: return err
    conn = sqlite3.connect(DB_FILE)
    try:
        rows = conn.execute(
            "SELECT id, wallet, role, invited_by, created_at FROM admin_invites "
            "WHERE status='pending' ORDER BY created_at DESC"
        ).fetchall()
        invites = [{
            'id': r[0], 'wallet': r[1], 'role': r[2],
            'invited_by': r[3], 'created_at': (r[4] or '')[:10],
        } for r in rows]
        return jsonify({'ok': True, 'invites': invites})
    finally:
        conn.close()


@app.route('/api/invite/check')
@csrf_exempt
def invite_check():
    wallet = session.get('wallet', '')
    if not wallet:
        return jsonify({'ok': False, 'invite': None})
    conn = sqlite3.connect(DB_FILE)
    try:
        row = conn.execute(
            "SELECT id, role, invited_by FROM admin_invites "
            "WHERE wallet=? AND status='pending' ORDER BY created_at DESC LIMIT 1",
            (wallet,)
        ).fetchone()
        if not row:
            return jsonify({'ok': True, 'invite': None})
        inv_by = row[2] or ''
        return jsonify({'ok': True, 'invite': {
            'id': row[0], 'role': row[1],
            'invited_by': (inv_by[:8] + '…') if len(inv_by) > 8 else inv_by,
        }})
    finally:
        conn.close()


@app.route('/api/invite/respond', methods=['POST'])
@csrf_exempt
def invite_respond():
    wallet = _authenticated_wallet()
    if not wallet:
        return jsonify({'ok': False, 'msg': 'Not authenticated'}), 401
    data      = request.get_json(silent=True) or {}
    action    = str(data.get('action', '')).strip()
    invite_id = data.get('invite_id')
    if action not in ('accept', 'decline'):
        return jsonify({'ok': False, 'msg': 'Invalid action'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        if invite_id:
            row = conn.execute(
                "SELECT id, role, invited_by FROM admin_invites "
                "WHERE id=? AND wallet=? AND status='pending'",
                (invite_id, wallet)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id, role, invited_by FROM admin_invites "
                "WHERE wallet=? AND status='pending' ORDER BY created_at DESC LIMIT 1",
                (wallet,)
            ).fetchone()
        if not row:
            return jsonify({'ok': False, 'msg': 'No pending invite found'}), 404
        inv_id, role, invited_by = row
        if action == 'accept':
            conn.execute(
                "UPDATE users SET role=? WHERE wallet_address=?",
                (role.lower(), wallet)
            )
            conn.execute(
                'INSERT INTO admin_roles(wallet_address,role,invited_by) VALUES(?,?,?) '
                'ON CONFLICT(wallet_address) DO UPDATE SET role=excluded.role',
                (wallet, role, invited_by or '')
            )
            conn.execute("UPDATE admin_invites SET status='accepted' WHERE id=?", (inv_id,))
            conn.commit()
            print(f'[invite] {wallet[:8]}… accepted role {role}', flush=True)
            return jsonify({'ok': True, 'role': role, 'msg': f'You are now a {role}'})
        else:
            conn.execute("UPDATE admin_invites SET status='declined' WHERE id=?", (inv_id,))
            conn.commit()
            print(f'[invite] {wallet[:8]}… declined role {role}', flush=True)
            return jsonify({'ok': True, 'msg': 'Invite declined'})
    finally:
        conn.close()


@app.route('/api/admin/role/change', methods=['POST'])
@csrf_exempt
def admin_role_change():
    wallet = _authenticated_wallet()
    if not wallet or not hmac.compare_digest(wallet.encode(), ADMIN_WALLET.encode()):
        return jsonify({'ok': False, 'msg': 'Forbidden'}), 403
    data        = request.get_json(silent=True) or {}
    target      = str(data.get('wallet', '')).strip()
    role        = str(data.get('role', '')).strip()
    if not target or len(target) < 32:
        return jsonify({'ok': False, 'msg': 'Invalid wallet'}), 400
    if target == ADMIN_WALLET:
        return jsonify({'ok': False, 'msg': 'Cannot change owner role'}), 400
    if role not in ('Moderator', 'Analyst', 'Executive'):
        return jsonify({'ok': False, 'msg': 'Invalid role'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute(
            'UPDATE admin_roles SET role=? WHERE wallet_address=?', (role, target)
        )
        conn.commit()
        print(f'[admin] role change {target[:8]}… → {role} by {wallet[:8]}…', flush=True)
        return jsonify({'ok': True, 'wallet': target, 'role': role})
    finally:
        conn.close()


@app.route('/api/admin/role/remove', methods=['POST'])
@csrf_exempt
def admin_role_remove():
    wallet = _authenticated_wallet()
    if not wallet or not hmac.compare_digest(wallet.encode(), ADMIN_WALLET.encode()):
        return jsonify({'ok': False, 'msg': 'Forbidden'}), 403
    data   = request.get_json(silent=True) or {}
    target = str(data.get('wallet', '')).strip()
    if not target or len(target) < 32:
        return jsonify({'ok': False, 'msg': 'Invalid wallet'}), 400
    if target == ADMIN_WALLET:
        return jsonify({'ok': False, 'msg': 'Cannot remove owner'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute('DELETE FROM admin_roles WHERE wallet_address=?', (target,))
        # get_user_role() falls back to users.role when no admin_roles row exists —
        # reset it too, otherwise the stale value keeps the old role in effect.
        conn.execute("UPDATE users SET role='user' WHERE wallet_address=?", (target,))
        conn.commit()
        print(f'[admin] role removed {target[:8]}… by {wallet[:8]}…', flush=True)
        return jsonify({'ok': True})
    finally:
        conn.close()


@app.route('/api/admin/clear_ratelimit', methods=['POST'])
@rate_limit(10, 60)
def admin_clear_ratelimit():
    """Clear IP ban and rate-limit hit counters.
    POST body: {"ip": "1.2.3.4"} to target one IP, or {} to clear everything."""
    err = _require_role('admin', 'executive', 'moderator')
    if err: return err
    wallet = _current_wallet()
    data   = request.json or {}
    target = (data.get('ip') or '').strip()
    if target:
        banned = target in _ip_ban
        _ip_ban.pop(target, None)
        _ip_warn.pop(target, None)
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute('DELETE FROM banned_ips WHERE ip=?', (target,))
            conn.commit()
            conn.close()
        except Exception:
            pass
        with _rl_lock:
            keys = [k for k in list(_rl_hits) if k.endswith(':' + target)]
            for k in keys:
                del _rl_hits[k]
        print(f'[admin] clear_ratelimit: {wallet[:8]}… cleared IP {target} '
              f'(was_banned={banned}, rl_buckets={len(keys)})', flush=True)
        return jsonify({'ok': True,
                        'msg': f'Cleared {target} — ban removed: {banned}, '
                               f'rate-limit buckets cleared: {len(keys)}'})
    else:
        n_bans = len(_ip_ban)
        n_rl   = len(_rl_hits)
        _ip_ban.clear()
        _ip_warn.clear()
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.execute('DELETE FROM banned_ips')
            conn.commit()
            conn.close()
        except Exception:
            pass
        with _rl_lock:
            _rl_hits.clear()
        print(f'[admin] clear_ratelimit: {wallet[:8]}… cleared ALL '
              f'({n_bans} bans, {n_rl} rl buckets)', flush=True)
        return jsonify({'ok': True,
                        'msg': f'Cleared all — {n_bans} ban(s) and {n_rl} rate-limit bucket(s) removed (permanent code-level bans unaffected)'})


@app.route('/api/admin/test', methods=['POST'])
@rate_limit(5, 60)
def admin_test():
    """Test live connectivity for Claude API and other integrations."""
    _log_readonly_attempt()
    wallet = _authenticated_wallet()
    if not wallet or not _is_owner(wallet):
        return jsonify({'error': 'Unauthorized'}), 403
    results = {}
    # ── Claude API ──
    if ANTHROPIC_API_KEY:
        try:
            resp = requests.post(
                _ANTHROPIC_URL,
                headers={**_ANTHROPIC_HEADERS, 'x-api-key': ANTHROPIC_API_KEY},
                json={'model': 'claude-haiku-4-5-20251001', 'max_tokens': 5,
                      'messages': [{'role': 'user', 'content': 'Reply with just: ok'}]},
                timeout=10,
            )
            if resp.status_code == 200:
                results['ai'] = {'ok': True,  'msg': 'Claude API key is valid ✓'}
                global _ai_disabled_until
                _ai_disabled_until = 0.0  # clear any backoff
            elif resp.status_code == 401:
                results['ai'] = {'ok': False, 'msg': 'Invalid API key (401)'}
            elif resp.status_code == 429:
                results['ai'] = {'ok': False, 'msg': 'Rate limited — key is valid but quota hit (429)'}
            else:
                results['ai'] = {'ok': False, 'msg': f'Unexpected HTTP {resp.status_code}'}
        except Exception as e:
            results['ai'] = {'ok': False, 'msg': str(e)[:100]}
    else:
        results['ai'] = {'ok': False, 'msg': 'ANTHROPIC_API_KEY not set in environment'}
    return jsonify(results)

@app.route('/api/admin/test_fee', methods=['POST'])
@rate_limit(3, 300)
def admin_test_fee():
    """Verify the full fee-transfer path step-by-step.
    If sender == receiver (owner testing with their own key), infrastructure is
    checked without sending — the SPL token program forbids self-transfers."""
    _log_readonly_attempt()
    import traceback as _tb
    wallet = _authenticated_wallet()
    if not wallet or not _is_owner(wallet):
        return jsonify({'error': 'Unauthorized'}), 403

    steps = []

    def _step(msg, ok=True, detail=''):
        entry = {'msg': msg, 'ok': ok, 'detail': detail}
        steps.append(entry)
        print(f'[test_fee] {"✓" if ok else "✗"} {msg}' + (f': {detail}' if detail else ''), flush=True)

    # ── 1. Trading key ──────────────────────────────────────────────────────
    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute('SELECT encrypted_private_key FROM users WHERE wallet_address=?', (wallet,))
        row = c.fetchone()
    finally:
        conn.close()
    if not row or not (row[0] or '').strip():
        _step('Trading key', ok=False, detail='No trading key saved — add your private key in Settings first')
        return jsonify({'ok': False, 'steps': steps, 'error': steps[-1]['detail']}), 400
    _step('Trading key', detail='found in DB')

    sig = None
    try:
        from solders.keypair import Keypair as _KP
        from solders.pubkey import Pubkey as _PK

        with _use_key(row[0], wallet) as pk:
            # ── 2. Keypair ──────────────────────────────────────────────────
            kp     = _KP.from_base58_string(pk)
            sender = kp.pubkey()
            _step('Keypair', detail=str(sender)[:8] + '…')

            # ── 3. SOL balance ──────────────────────────────────────────────
            bal_r   = requests.post(SOLANA_RPC, json={
                'jsonrpc': '2.0', 'id': 1, 'method': 'getBalance', 'params': [str(sender)],
            }, timeout=10).json()
            lamports = (bal_r.get('result') or {}).get('value', 0)
            balance  = lamports / 1e9
            _step('SOL balance', detail=f'{balance:.6f} SOL')
            if balance < 0.001:
                _step('Balance check', ok=False,
                      detail=f'Insufficient SOL: {balance:.6f} (need ≥ 0.001 SOL for test transfer + fees)')
                return jsonify({'ok': False, 'steps': steps, 'error': steps[-1]['detail']}), 400
            _step('Balance check', detail='sufficient')

            # ── 4. Self-transfer guard ──────────────────────────────────────
            # Native SOL self-transfer is technically valid on-chain but wastes fees.
            # When owner tests with their own key, sender == OWNER_WALLET — just
            # confirm infrastructure is wired up without burning lamports.
            if _is_owner(str(sender)):
                _step('Transfer skipped',
                      detail='sender == OWNER_WALLET (owner self-transfer). '
                             'All infrastructure verified ✓ — no lamports wasted.')
                return jsonify({
                    'ok':   True,
                    'steps': steps,
                    'msg':  'Infrastructure verified — key, balance, and RPC all OK. '
                            'Transfer skipped: sender is OWNER_WALLET.',
                })

            # ── 5. Send 0.0001 SOL ──────────────────────────────────────────
            _step('Building SOL transfer…')
            sig = send_sol_fee(pk, OWNER_WALLET, 0.0001)
            _step('Transaction sent', detail=sig[:16] + '…')

        _log_security_event('key_access', wallet, 'test_fee_transfer 0.0001 SOL')
        return jsonify({
            'ok':          True,
            'steps':       steps,
            'sig':         sig,
            'solscan_url': 'https://solscan.io/tx/' + sig,
            'msg':         'Sent 0.0001 SOL successfully',
        })

    except Exception as e:
        tb = _tb.format_exc()
        print(f'[test_fee] EXCEPTION:\n{tb}', flush=True)  # server log only — never sent to client
        _step('Error', ok=False, detail=str(e)[:120])
        return jsonify({'ok': False, 'steps': steps, 'error': str(e)[:120]}), 500

@app.route('/api/admin/rotate_keys', methods=['POST'])
@rate_limit(1, 300)
def admin_rotate_keys():
    """Re-encrypt all stored private keys with a new ENCRYPTION_KEY.
    After rotating, update the ENCRYPTION_KEY env var and redeploy."""
    _log_readonly_attempt()
    wallet = _authenticated_wallet()
    if not wallet or not _is_owner(wallet):
        return jsonify({'error': 'Unauthorized'}), 403
    new_enc_key = (request.json or {}).get('new_encryption_key', '').strip()
    if not new_enc_key:
        return jsonify({'ok': False, 'msg': 'new_encryption_key required in request body'}), 400
    try:
        new_fernet = Fernet(new_enc_key.encode())
    except Exception:
        return jsonify({'ok': False, 'msg': 'Invalid Fernet key format — generate with Fernet.generate_key()'}), 400

    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute("SELECT wallet_address, encrypted_private_key FROM users WHERE encrypted_private_key != '' AND encrypted_private_key IS NOT NULL")
        rows = c.fetchall()
        migrated = failed = 0
        for waddr, enc_blob in rows:
            raw = None
            try:
                raw      = decrypt_private_key(enc_blob, waddr)
                l1       = new_fernet.encrypt(raw.encode())
                derived  = hmac.digest(new_enc_key.encode(), waddr.encode(), 'sha256')
                new_wf   = Fernet(base64.urlsafe_b64encode(derived))
                l2       = new_wf.encrypt(l1)
                new_enc  = 'v2:' + l2.decode()
                new_hash = hashlib.sha256(raw.encode()).hexdigest()
                c.execute('UPDATE users SET encrypted_private_key=?, key_hash=? WHERE wallet_address=?',
                          (new_enc, new_hash, waddr))
                migrated += 1
            except Exception:
                failed += 1
            finally:
                raw = None  # clear immediately
        conn.commit()
    finally:
        conn.close()

    _log_security_event('key_rotation', wallet, f'{migrated} migrated, {failed} failed')
    return jsonify({
        'ok':       True,
        'migrated': migrated,
        'failed':   failed,
        'note':     'Now update ENCRYPTION_KEY in your environment to the new key and redeploy',
    })

@app.route('/api/admin/security-status')
@rate_limit(20, 60)
def admin_security_status():
    """Real-time snapshot of all security checks, consecutive failure count, and trading pause state."""
    _log_readonly_attempt()
    wallet = _authenticated_wallet()
    if not wallet or not _is_owner(wallet):
        return jsonify({'error': 'Unauthorized'}), 403
    failures = _run_security_checks()
    now = time.time()
    # Summarise multi-IP wallets (2+ distinct IPs in last hour)
    with _wallet_ips_lock:
        multi_ip = {
            w: len({h for h, _ in entries})
            for w, entries in _wallet_ips.items()
            if len({h for h, ts in entries if now - ts < 3600}) >= 2
        }
    all_checks = [{'name': c['check'], 'ok': False, 'detail': c['detail']} for c in failures]
    passing = {c['check'] for c in failures}
    _known = ['ENCRYPTION_KEY', 'Key Decryption', 'Response Schema', 'Honeypots', 'Rate Limiter']
    for name in _known:
        if name not in passing:
            all_checks.append({'name': name, 'ok': True, 'detail': ''})
    return jsonify({
        'ok':                   len(failures) == 0,
        'checks':               all_checks,
        'consecutive_failures': _sec_check_state['consecutive_failures'],
        'trading_paused':       _sec_check_state['trading_paused'],
        'paused_at':            _sec_check_state.get('paused_at'),
        'last_checked':         _sec_check_state.get('last_checked'),
        'last_failures':        _sec_check_state.get('last_failures', []),
        'ip_bans_active':       sum(1 for exp in _ip_ban.values() if now < exp),
        'active_traders':       sum(1 for us in user_states.values() if us.get('trader_running')),
        'multi_ip_wallets':     multi_ip,
        'ran_at':               datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
    })

# How far back the key-event and readonly-attempt checks look.
_AUDIT_WINDOW_DAYS = 14
# A privileged account with no heartbeat in this many days is flagged as stale.
_AUDIT_STALE_ROLE_DAYS = 30

@app.route('/api/admin/security-audit', methods=['POST'])
@rate_limit(6, 60)
def admin_security_audit():
    """On-demand security audit for the admin dashboard's Security tab.

    Three checks, all read-only:
    1. Recent key_revealed/sol_sent/send_failed events, enriched with whether the
       wallet is a known active trader and same-IP anomalies (mirrors the manual
       analyze_reveal_send.sql incident-response query, but windowed + reusable).
    2. Privileged (admin/moderator/analyst) accounts with no heartbeat in
       _AUDIT_STALE_ROLE_DAYS days — dormant accounts that still hold access.
    3. readonly_privileged_attempt hits — read-only sessions that got 403'd by
       _require_role(), the exact pattern behind the read-only privilege-escalation
       fix (see _authenticated_wallet()).
    """
    err = _require_role('admin', 'executive', 'moderator')
    if err: return err
    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()

        # ── Check 1: key_revealed / sol_sent / send_failed ──
        c.execute('''
            WITH hits AS (
                SELECT id, timestamp, ip_addr, wallet AS wallet_short, event_type, details
                FROM security_log
                WHERE event_type IN ('key_revealed','sol_sent','send_failed')
                  AND timestamp >= datetime('now', ?)
            ),
            user_lookup AS (
                SELECT id, wallet_address,
                       substr(wallet_address,1,4) || '...' || substr(wallet_address,-4) AS wallet_short,
                       (encrypted_private_key IS NOT NULL AND encrypted_private_key != '') AS has_key
                FROM users
            ),
            trade_counts AS (
                SELECT user_id, COUNT(*) AS trade_count, MAX(timestamp) AS last_trade
                FROM trades GROUP BY user_id
            ),
            ip_stats AS (
                SELECT h1.id,
                    (SELECT COUNT(*) FROM hits h2 WHERE h2.ip_addr = h1.ip_addr AND h2.id != h1.id
                       AND ABS(strftime('%s', h2.timestamp) - strftime('%s', h1.timestamp)) <= 60
                    ) AS same_ip_60s,
                    (SELECT COUNT(DISTINCT wallet_short) FROM hits h3 WHERE h3.ip_addr = h1.ip_addr
                    ) AS distinct_wallets_ip
                FROM hits h1
            )
            SELECT h.timestamp, h.ip_addr, h.wallet_short, h.event_type, h.details,
                   u.id, u.has_key, tc.trade_count, tc.last_trade,
                   ips.same_ip_60s, ips.distinct_wallets_ip
            FROM hits h
            LEFT JOIN user_lookup  u   ON u.wallet_short = h.wallet_short
            LEFT JOIN trade_counts tc  ON tc.user_id = u.id
            LEFT JOIN ip_stats     ips ON ips.id = h.id
            ORDER BY h.timestamp DESC
            LIMIT 200
        ''', (f'-{_AUDIT_WINDOW_DAYS} days',))
        key_events = []
        for ts, ip, wshort, etype, details, uid, has_key, trade_count, last_trade, same_ip_60s, distinct_wallets in c.fetchall():
            trade_count = trade_count or 0
            if uid is None:
                wallet_status, wallet_status_label = 'unknown', 'Unknown — no matching user for this wallet'
            elif has_key and trade_count > 0:
                wallet_status = 'known_trader'
                wallet_status_label = f'Known active trader — {trade_count} trade(s), last {last_trade}'
            elif has_key:
                wallet_status, wallet_status_label = 'key_no_trades', 'Key stored, never traded'
            else:
                wallet_status, wallet_status_label = 'no_key', 'No trading key stored'

            ip_anomaly = None
            if same_ip_60s:
                ip_anomaly = f'{same_ip_60s} other hit(s) from this IP within 60s'
            elif distinct_wallets and distinct_wallets > 1:
                ip_anomaly = f'this IP touched {distinct_wallets} different wallets'

            key_events.append({
                'ts': ts, 'ip': ip, 'wallet_short': wshort, 'event_type': etype,
                'details': _redact_keys(str(details or '')),
                'wallet_status': wallet_status, 'wallet_status_label': wallet_status_label,
                'ip_anomaly': ip_anomaly,
            })

        # ── Check 2: stale privileged accounts ──
        c.execute('''
            SELECT wallet_address, role, 'admin_roles' AS source FROM admin_roles
            UNION
            SELECT wallet_address, role, 'users.role' AS source FROM users
            WHERE role IS NOT NULL AND lower(role) IN ('admin','executive','moderator','analyst')
              AND wallet_address NOT IN (SELECT wallet_address FROM admin_roles)
        ''')
        privileged = c.fetchall()
        stale_accounts = []
        for waddr, role, source in privileged:
            if waddr == ADMIN_WALLET:
                continue  # constant super-admin wallet, not a delegated/revocable grant
            row = conn.execute(
                'SELECT last_active, created_at FROM users WHERE wallet_address=?', (waddr,)
            ).fetchone()
            last_active, created_at = row if row else (None, None)
            wshort = (waddr[:4] + '...' + waddr[-4:]) if len(waddr) >= 8 else waddr
            if not last_active:
                status, days_inactive = 'never_active', None
            else:
                try:
                    days_inactive = (datetime.datetime.utcnow() -
                                      datetime.datetime.fromisoformat(last_active.replace(' ', 'T'))).days
                except Exception:
                    days_inactive = None
                status = 'stale' if (days_inactive is None or days_inactive >= _AUDIT_STALE_ROLE_DAYS) else 'ok'
            stale_accounts.append({
                'wallet': waddr, 'wallet_short': wshort, 'role': (role or '').lower(),
                'source': source, 'last_active': last_active, 'created_at': created_at,
                'days_inactive': days_inactive, 'status': status,
            })
        stale_accounts.sort(key=lambda a: (a['status'] != 'stale', a['status'] != 'never_active'))

        # ── Check 3: readonly sessions that hit privileged routes ──
        c.execute('''
            SELECT timestamp, wallet, ip_addr, details FROM security_log
            WHERE event_type='readonly_privileged_attempt'
              AND timestamp >= datetime('now', ?)
            ORDER BY timestamp DESC
            LIMIT 100
        ''', (f'-{_AUDIT_WINDOW_DAYS} days',))
        readonly_attempts = [
            {'ts': r[0], 'wallet_short': r[1], 'ip': r[2], 'path': r[3]}
            for r in c.fetchall()
        ]

        return jsonify({
            'ok': True,
            'ran_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'window_days': _AUDIT_WINDOW_DAYS,
            'key_events': {
                'items': key_events,
                'flagged': sum(1 for e in key_events if e['ip_anomaly']),
            },
            'stale_accounts': {
                'items': stale_accounts,
                'flagged': sum(1 for a in stale_accounts if a['status'] in ('stale', 'never_active')),
            },
            'readonly_attempts': {
                'items': readonly_attempts,
                'flagged': len(readonly_attempts),
            },
        })
    except Exception as e:
        return jsonify({'ok': False, 'msg': str(e)[:200]}), 500
    finally:
        conn.close()

@app.route('/api/admin/test_trade', methods=['POST'])
@rate_limit(3, 300)
def admin_test_trade():
    """Execute a $1 USDC test buy using the owner's saved trading key.
    Returns the full subprocess stdout/stderr so you can verify the on-chain path
    without waiting for the bot to find a signal naturally."""
    _log_readonly_attempt()
    wallet = _authenticated_wallet()
    if not wallet or not _is_owner(wallet):
        return jsonify({'error': 'Unauthorized'}), 403

    token_address = ((request.json or {}).get('token_address', '') or '').strip()
    if not token_address or not _SOLANA_ADDR_RE.match(token_address):
        return jsonify({'error': 'token_address must be a valid Solana mint address'}), 400

    # Fetch owner's encrypted key from DB
    conn = sqlite3.connect(DB_FILE)
    try:
        c = conn.cursor()
        c.execute('SELECT encrypted_private_key FROM users WHERE wallet_address=?', (wallet,))
        row = c.fetchone()
    finally:
        conn.close()

    if not row or not (row[0] or '').strip():
        return jsonify({'error': 'No trading key saved for owner wallet — add it in Settings first'}), 400

    enc_blob = row[0]
    start_ts = time.time()

    try:
        with _use_key(enc_blob, wallet) as pk:
            env = os.environ.copy()
            env['WALLET_ADDRESS']     = wallet
            env['WALLET_PRIVATE_KEY'] = pk
            proc = subprocess.run(
                [sys.executable, os.path.join(BASE, 'orcagent_solana.py'),
                 'buy', token_address, '1.0'],
                env=env, capture_output=True, text=True, timeout=60,
            )
            env['WALLET_PRIVATE_KEY'] = ''
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    elapsed = round(time.time() - start_ts, 2)
    stdout  = proc.stdout.strip()
    stderr  = proc.stderr.strip()

    # Extract Solscan URL from output before redacting (TX hash is in the URL path)
    solscan_url = ''
    for line in stdout.splitlines():
        if 'solscan.io/tx/' in line:
            idx = line.find('https://')
            if idx >= 0:
                solscan_url = line[idx:].strip()
                break

    _log_security_event('key_access', wallet, f'test_trade {token_address[:8]}')

    return jsonify({
        'ok':          proc.returncode == 0 and bool(solscan_url),
        'returncode':  proc.returncode,
        'stdout':      _redact_keys(stdout),
        'stderr':      _redact_keys(stderr),
        'solscan_url': solscan_url,
        'elapsed_s':   elapsed,
    })

# ── AI SELF-ANALYSIS ADMIN ──
@app.route('/api/admin/ai-filters', methods=['GET'])
def admin_ai_filters():
    """Current active filters + recent proposals (pending first) for the
    admin dashboard's AI Filters tab. Read access for the same roles that
    can already see the rest of the admin dashboard."""
    err = _require_role('admin', 'executive', 'moderator', 'analyst')
    if err: return err
    conn = sqlite3.connect(DB_FILE)
    try:
        rows = conn.execute(
            '''SELECT id, proposed_json, reasoning, trades_analyzed, status,
                      reviewed_by, reviewed_at, created_at, how_analysis
               FROM ai_filter_proposals ORDER BY id DESC LIMIT 20'''
        ).fetchall()
    finally:
        conn.close()
    proposals = [{
        'id': r[0], 'proposed': json.loads(r[1]), 'reasoning': r[2],
        'trades_analyzed': r[3], 'status': r[4], 'reviewed_by': r[5],
        'reviewed_at': r[6], 'created_at': r[7], 'how_analysis': r[8] or '',
    } for r in rows]
    return jsonify({'ok': True, 'active_filters': get_ai_active_filters(), 'proposals': proposals})

@app.route('/api/admin/ai-filters/run-now', methods=['POST'])
@rate_limit(6, 3600)
def admin_ai_filters_run_now():
    """Manual trigger for run_ai_self_analysis() -- same purpose as
    /admin/narrative-test: verify the pipeline works without waiting for the
    daily schedule. Still only ever produces a pending proposal."""
    err = _require_role('admin', 'executive')
    if err: return err
    result = run_ai_self_analysis()
    return jsonify(result), (200 if result.get('ok') else 400)

@app.route('/api/admin/ai-filters/approve', methods=['POST'])
@rate_limit(20, 3600)
def admin_ai_filters_approve():
    wallet = _authenticated_wallet()
    err = _require_role('admin', 'executive')
    if err: return err
    proposal_id = (request.get_json(silent=True) or {}).get('proposal_id')
    if not proposal_id:
        return jsonify({'ok': False, 'msg': 'proposal_id required'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        row = conn.execute('SELECT proposed_json, status FROM ai_filter_proposals WHERE id=?',
                            (proposal_id,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'msg': 'proposal not found'}), 404
        if row[1] != 'pending':
            return jsonify({'ok': False, 'msg': f'proposal already {row[1]}'}), 400
        conn.execute("INSERT OR REPLACE INTO server_config (key, value) VALUES ('ai_active_filters', ?)",
                     (row[0],))
        conn.execute(
            "UPDATE ai_filter_proposals SET status='approved', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP WHERE id=?",
            (wallet, proposal_id))
        conn.commit()
    finally:
        conn.close()
    _log_security_event('ai_filters_approved', wallet, f'proposal #{proposal_id}')
    print(f'[ai-filters] proposal #{proposal_id} approved by {wallet[:8]}… — now live', flush=True)
    return jsonify({'ok': True, 'active_filters': get_ai_active_filters()})

@app.route('/api/admin/ai-filters/reject', methods=['POST'])
@rate_limit(20, 3600)
def admin_ai_filters_reject():
    wallet = _authenticated_wallet()
    err = _require_role('admin', 'executive')
    if err: return err
    proposal_id = (request.get_json(silent=True) or {}).get('proposal_id')
    if not proposal_id:
        return jsonify({'ok': False, 'msg': 'proposal_id required'}), 400
    conn = sqlite3.connect(DB_FILE)
    try:
        cur = conn.execute(
            "UPDATE ai_filter_proposals SET status='rejected', reviewed_by=?, reviewed_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='pending'", (wallet, proposal_id))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'ok': False, 'msg': 'proposal not found or not pending'}), 404
    finally:
        conn.close()
    return jsonify({'ok': True})

# ── STARTUP ──
if not OWNER_WALLET:
    print('WARNING: OWNER_WALLET is not set in environment variables.')
    print('         is_admin will never be true for any user.')
    print('         Set OWNER_WALLET in /etc/orcagent.env and restart.')
elif OWNER_WALLET != ADMIN_WALLET:
    # Non-fatal by design -- OWNER_WALLET and ADMIN_WALLET are allowed to
    # differ (see the comment where they're defined), but in this app's
    # actual deployment they're meant to be the same address, so a mismatch
    # here almost certainly means one of them drifted (e.g. OWNER_WALLET
    # rotated without updating the hardcoded ADMIN_WALLET, or vice versa)
    # rather than being intentional.
    print('WARNING: OWNER_WALLET does not match the hardcoded ADMIN_WALLET.')
    print('         These are expected to be the same address in this deployment --')
    print('         promotion-payment verification, the super-admin role guard, and')
    print('         is_admin/_is_owner() checks may now disagree about who the owner is.')
init_db()

DISK_LOW_BYTES = 300 * 1024 * 1024   # start reclaiming below this

# ── image storage ───────────────────────────────────────────────────────────
# Every uploaded picture is kept as a base64 data URI in a TEXT column, so a
# photo does not land on the filesystem -- it lands in orcagent.db, and base64
# adds a third on top of it. A 3 MB phone photo becomes about 4 MB of database,
# a few hundred of them are gigabytes, and that database is what the volume
# holds and what every backup copies. That is what filled the volume.
#
# Nothing here changes where images are stored. What it changes is their size:
# a picture is re-encoded once, on the way in, to something no larger than the
# screens that display it actually need.

IMAGE_MAX_EDGE  = 1600            # px on the long side -- above any display size in the app
IMAGE_TARGET_KB = 400             # what a full-width photo should cost
IMAGE_AVATAR_EDGE = 512           # avatars and group icons are never shown larger


def _shrink_image_data_uri(data_uri: str, max_edge: int = IMAGE_MAX_EDGE,
                           target_kb: int = IMAGE_TARGET_KB) -> str:
    """Re-encode an uploaded data URI down to something sensible.

    Returns a data URI -- the shrunken one, or the ORIGINAL unchanged if it
    cannot be improved or anything goes wrong. This runs on the upload path of
    every picture in the app, so it must never be the reason a post fails: the
    size limits at each call site still apply either way, and this only ever
    makes the stored value smaller.

    Animated GIFs are returned untouched. Re-encoding one through a single
    frame would silently turn a user's animation into a still, which is worse
    than storing it whole.
    """
    try:
        if not data_uri or not data_uri.startswith('data:image/'):
            return data_uri
        header, _, b64_part = data_uri.partition(',')
        if not b64_part:
            return data_uri
        raw = base64.b64decode(b64_part, validate=True)
        img = Image.open(io.BytesIO(raw))

        # An animated GIF keeps its frames; a still one is fair game.
        if getattr(img, 'is_animated', False):
            return data_uri

        img.load()
        # Transparency has to survive, so anything with an alpha channel stays
        # PNG. Everything else becomes JPEG, which is what makes the saving.
        has_alpha = img.mode in ('RGBA', 'LA') or (
            img.mode == 'P' and 'transparency' in img.info)

        if max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge), Image.LANCZOS)

        buf = io.BytesIO()
        if has_alpha:
            img.convert('RGBA').save(buf, format='PNG', optimize=True)
            mime = 'image/png'
        else:
            rgb = img.convert('RGB')
            # Step the quality down until it fits, rather than picking one
            # number that is too low for a photo and too high for a screenshot.
            for quality in (85, 78, 70, 62, 55):
                buf = io.BytesIO()
                rgb.save(buf, format='JPEG', quality=quality, optimize=True,
                         progressive=True)
                if buf.tell() <= target_kb * 1024:
                    break
            mime = 'image/jpeg'

        out = buf.getvalue()
        if len(out) >= len(raw):
            # Already smaller than anything we would produce. Re-encoding it
            # would only lose quality for nothing.
            return data_uri
        return 'data:' + mime + ';base64,' + base64.b64encode(out).decode('ascii')
    except Exception as e:
        print(f'[image] could not shrink an upload, storing it as sent: '
              f'{type(e).__name__}: {e}', flush=True)
        return data_uri


def _shrink_image_bytes(data: bytes, ext: str) -> tuple:
    """The same re-encoding for the two endpoints that receive a real file
    rather than a data URI. Returns (bytes, extension), unchanged on any
    failure or when the original is already the smaller of the two.

    These land in static/ rather than on the data volume, so they are not what
    filled it -- but a 5 MB upload is 5 MB of container disk either way, and
    the file is served to phones that will never use the resolution.
    """
    try:
        uri = 'data:image/' + ('jpeg' if ext in ('jpg', 'jpeg') else ext) + \
              ';base64,' + base64.b64encode(data).decode('ascii')
        out = _shrink_image_data_uri(uri)
        if out is uri or not out.startswith('data:image/'):
            return data, ext
        header, _, b64_part = out.partition(',')
        new_ext = 'jpg' if 'jpeg' in header else ('png' if 'png' in header else ext)
        return base64.b64decode(b64_part), new_ext
    except Exception:
        return data, ext


def _stored_image_bytes() -> int:
    """How much of the database is pictures.

    Reported rather than acted on: these are user posts, and re-encoding
    content somebody already published is their call, not a maintenance job's.
    """
    total = 0
    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            for table, col in (('feed_posts', 'image_url'), ('group_posts', 'image_url'),
                               ('messages', 'content'), ('group_chat', 'content'),
                               ('users', 'avatar_url'), ('users', 'banner_url'),
                               ('groups', 'avatar_url'), ('groups', 'banner_url')):
                try:
                    row = conn.execute(
                        f"SELECT COALESCE(SUM(LENGTH({col})), 0) FROM {table} "
                        f"WHERE {col} LIKE 'data:image/%'").fetchone()
                    total += int((row or (0,))[0] or 0)
                except sqlite3.Error:
                    continue      # that table or column does not exist here
        finally:
            conn.close()
    except Exception:
        return 0
    return total


def _storage_breakdown() -> str:
    """One line naming what is actually on the data volume.

    Written after the volume filled up and nobody -- including me -- could
    say what was using it without a shell, which a hosted container does not
    give you. Knowing the database is 40 MB and the backups were 300 MB is
    the difference between guessing at a new volume size and choosing one."""
    def mb(n):
        return f'{n / (1024 * 1024):.0f} MB'
    try:
        db  = os.path.getsize(DB_FILE) if os.path.exists(DB_FILE) else 0
        wal = os.path.getsize(DB_FILE + '-wal') if os.path.exists(DB_FILE + '-wal') else 0
        # Counted the same way it is sized. The size used to include every
        # file in the directory while the count only included the ones the app
        # writes itself, so "497 MB (3 files)" was two different sets of files
        # in one sentence -- and it made the deploy script's own copies look
        # like the app's backups had grown enormous.
        bk = 0
        bk_n = 0
        if os.path.isdir(BACKUP_DIR):
            for f in os.listdir(BACKUP_DIR):
                try:
                    bk += os.path.getsize(os.path.join(BACKUP_DIR, f))
                    bk_n += 1
                except OSError:
                    pass
        used  = shutil.disk_usage(_DATA_DIR)
        # Its own try: the image total needs a database query, and losing the
        # whole storage line because that one query failed would take away
        # exactly the information you need when the volume is full.
        try:
            img_part = f' (of which images {mb(_stored_image_bytes())})'
        except Exception:
            img_part = ''
        own = len(_backup_files())
        extra = bk_n - own
        return (f'db {mb(db)}{img_part} · wal {mb(wal)} · '
                f'backups {mb(bk)} ({bk_n} files'
                + (f', {own} mine + {extra} other' if extra else '') + ') · '
                f'volume {mb(used.used)} used of {mb(used.total)}, {mb(used.free)} free')
    except Exception as e:
        return f'could not read storage: {e}'

def _reclaim_disk_space() -> int:
    """Free space on the data volume without touching anything a user owns.

    Only two things here are disposable: old database backups (by definition
    copies of something we still have) and the write-ahead log, which a
    checkpoint retires. Trades, calls, posts and settings are never touched.
    Returns the bytes recovered."""
    freed = 0
    before = _free_bytes()

    n = len(_backup_files())
    if n > 1:
        freed += _prune_backups(keep=1)     # keep the newest, always
        print(f'[startup] pruned {n - 1} old backup(s) to free space', flush=True)

    try:
        wal = DB_FILE + '-wal'
        wal_before = os.path.getsize(wal) if os.path.exists(wal) else 0
        if wal_before:
            conn = sqlite3.connect(DB_FILE, isolation_level=None)
            try:
                conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            finally:
                conn.close()
            wal_after = os.path.getsize(wal) if os.path.exists(wal) else 0
            freed += max(0, wal_before - wal_after)
            print(f'[startup] checkpointed WAL: {wal_before // (1024*1024)} MB -> '
                  f'{wal_after // (1024*1024)} MB', flush=True)
    except Exception as e:
        print(f'[startup] WAL checkpoint failed: {e}', flush=True)

    after = _free_bytes()
    if before >= 0 and after >= 0:
        freed = max(freed, after - before)
    return freed

def _db_write_selftest():
    """Prove at startup that the database can actually be WRITTEN to -- and
    if the volume is nearly full, reclaim what can be reclaimed first.

    Reads kept working while every write failed, which is the signature of a
    full volume or a read-only mount, and nothing in the app said so: the
    only symptom was an error on whichever button the user happened to press.
    This is where that becomes visible, and where it gets fixed if it can be
    fixed without anyone's help -- the volume filling up is not something a
    non-technical owner can clear by hand on a hosted container.

    Never raises: a diagnostic that can stop the app from starting is worse
    than the problem it reports."""
    free = _free_bytes()
    free_mb = free / (1024 * 1024) if free >= 0 else -1

    if 0 <= free < DISK_LOW_BYTES:
        print(f'[startup] ⚠ only {free_mb:.0f} MB free on {_DATA_DIR} — reclaiming', flush=True)
        got = _reclaim_disk_space()
        free = _free_bytes()
        free_mb = free / (1024 * 1024) if free >= 0 else -1
        print(f'[startup] reclaimed {got // (1024*1024)} MB — now {free_mb:.0f} MB free', flush=True)
        if 0 <= free < DISK_LOW_BYTES:
            print('[startup] ⚠ STILL LOW. Free more space or grow the volume; the '
                  'database cannot keep writing on a full disk.', flush=True)
    try:
        conn = sqlite3.connect(DB_FILE)
        try:
            conn.execute('CREATE TABLE IF NOT EXISTS _write_selftest (id INTEGER PRIMARY KEY, ts TEXT)')
            conn.execute('INSERT INTO _write_selftest (ts) VALUES (?)', (str(time.time()),))
            conn.execute('DELETE FROM _write_selftest')
            conn.commit()
        finally:
            conn.close()
        print(f'[startup] database is writable', flush=True)
        print(f'[startup] storage: {_storage_breakdown()}', flush=True)
        if 0 <= free_mb < 50:
            print(f'[startup] ⚠ only {free_mb:.0f} MB free — writes will start failing soon', flush=True)
    except Exception as e:
        print(f'[startup] ✗ DATABASE IS NOT WRITABLE: {type(e).__name__}: {e}', flush=True)
        print(f'[startup]   storage: {_storage_breakdown()}', flush=True)
        print('[startup]   every write (calls, trades, settings) will fail until this is fixed', flush=True)

_db_write_selftest()
run_migrations()
_encrypt_legacy_x_tokens()
_load_banned_ips()
def _heartbeat_loop():
    while True:
        try:
            ts = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            with open(HEARTBEAT_FILE, 'w') as _hf:
                _hf.write(ts)
        except Exception as _e:
            print(f'[heartbeat] write error: {_e}', flush=True)
        time.sleep(60)

threading.Thread(target=_heartbeat_loop,       daemon=True).start()
threading.Thread(target=token_loop,            daemon=True).start()
threading.Thread(target=_fast_poll_loop,       daemon=True).start()
threading.Thread(target=_bridge_status_loop,   daemon=True).start()
threading.Thread(target=_calls_peak_loop,      daemon=True).start()
threading.Thread(target=bsc_token_loop,        daemon=True).start()
threading.Thread(target=totd_loop,             daemon=True).start()
threading.Thread(target=_cleanup_loop,         daemon=True).start()
threading.Thread(target=_audit_loop,           daemon=True).start()
threading.Thread(target=_security_check_loop,  daemon=True).start()
import gas_manager
threading.Thread(target=gas_manager.gas_sweep_loop, daemon=True).start()
import surge_radar
threading.Thread(target=surge_radar.surge_loop, daemon=True).start()
# Tells the operator, at a glance, which address to keep funded with native
# gas on each EVM chain (or that sponsorship is simply off). Never prints the
# key itself -- only the public address derived from it.
if not OWNER_WALLETS:
    print('[startup] ⚠ no owner wallet configured — every owner-only admin action '
          '(Collect Fees, key rotation, the gas sponsor panel) will refuse for everyone, '
          'including you. Set OWNER_WALLET in /etc/orcagent.env to the wallet you sign '
          'in with, then restart.', flush=True)
else:
    # Printed so "why was I refused?" is answerable from the logs alone,
    # without guessing whether the env var matches the wallet you sign in
    # with. Addresses only; nothing secret is involved in owning one.
    print('[startup] owner wallets (full admin rights): '
          + ', '.join(sorted(OWNER_WALLETS)), flush=True)
_gs_addr = _gas_sponsor_address()
print(f'[startup] gas sponsor wallet (EVM): {_gs_addr} — keep this funded with native gas on each EVM chain'
      if _gs_addr else
      '[startup] EVM gas sponsorship DISABLED (no GAS_SPONSOR_PRIVATE_KEY) — empty EVM wallets fall back to a SOL bootstrap bridge',
      flush=True)
_gs_sol_addr = _sol_gas_sponsor_address()
print(f'[startup] gas sponsor wallet (Solana): {_gs_sol_addr} — keep this funded with SOL'
      if _gs_sol_addr else
      '[startup] Solana gas sponsorship DISABLED (no SOL_GAS_SPONSOR_PRIVATE_KEY) — users need their own SOL for network fees',
      flush=True)
_security_selftest()
add_log('OrcAgent started')
def _autostart_bots():
    """Re-start bots for users who had bot_enabled=1 before the last deploy.
    Runs in a background thread so it doesn't block Flask startup."""
    time.sleep(5)  # let DB init and migrations finish
    try:
        _conn = sqlite3.connect(DB_FILE)
        _rows = _conn.execute(
            "SELECT wallet_address FROM users "
            "WHERE bot_enabled=1 AND encrypted_private_key != '' AND encrypted_private_key IS NOT NULL"
        ).fetchall()
        _n_total = _conn.execute(
            "SELECT COUNT(*) FROM users WHERE encrypted_private_key != '' AND encrypted_private_key IS NOT NULL"
        ).fetchone()[0]
        _conn.close()
    except Exception as _e:
        print(f'[startup] autostart query failed: {_e}', flush=True)
        return
    print(f'[startup] {len(_rows)} bot(s) set to auto-restart  '
          f'({_n_total} user{"s" if _n_total != 1 else ""} with trading key configured)', flush=True)
    for (_wal,) in _rows:
        try:
            us = get_user_state(_wal)
            if us.get('trader_running'):
                continue
            us['trader_stop']   = threading.Event()
            us['trader_thread'] = threading.Thread(
                target=user_trader_loop, args=(us['trader_stop'], {}, _wal), daemon=True)
            us['trader_thread'].start()
            us['trader_running'] = True
            _sh = (_wal[:6] + '...' + _wal[-4:]) if len(_wal) >= 10 else _wal
            print(f'[startup] auto-restarted bot for {_sh}', flush=True)
            add_user_log(_wal, f'[{_sh}] Bot auto-restarted after deploy')
        except Exception as _e2:
            print(f'[startup] failed to auto-restart {_wal[:8]}: {_e2}', flush=True)

threading.Thread(target=_autostart_bots, daemon=True).start()

def _startup_fee_recovery():
    """One-time recovery run 30 s after boot — collects any fees missed before fee_paid tracking."""
    time.sleep(30)
    print('[fee-recovery] startup pass — checking for unpaid fees...', flush=True)
    _recover_uncollected_fees(triggered_by='startup')

threading.Thread(target=_startup_fee_recovery, daemon=True).start()

# ── DAILY DATABASE BACKUP ────────────────────────────────────────────────────
def backup_database() -> bool:
    """
    Hot-copy orcagent.db to BACKUP_DIR/orcagent_YYYY-MM-DD.db.gz using the
    sqlite3 online backup API (safe under concurrent reads/writes), then
    gzip it.

    Backups are gzipped and capped at BACKUP_KEEP because this directory is
    what filled the volume: seven UNCOMPRESSED copies of the database is
    eight times the database's own size sitting next to it, on the same
    volume, and when that volume fills every write in the app starts failing
    with "database or disk is full" while reads carry on working normally.
    A SQLite file compresses several times over, so this is roughly a
    ten-fold reduction in what backups cost.

    It also refuses to run when space is already short. A backup that tips
    the volume over does more harm than a missing day of backups.
    """
    free = _free_bytes()
    if 0 <= free < BACKUP_MIN_FREE_BYTES:
        print(f'[backup] skipped — only {free // (1024*1024)} MB free; pruning instead', flush=True)
        _prune_backups()
        return False
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        date_str  = datetime.datetime.utcnow().strftime('%Y-%m-%d')
        tmp_path  = os.path.join(BACKUP_DIR, f'.orcagent_{date_str}.tmp')
        dest_path = os.path.join(BACKUP_DIR, f'orcagent_{date_str}.db.gz')
        # Use sqlite3 online backup so we never read a torn page
        src  = sqlite3.connect(DB_FILE)
        dest = sqlite3.connect(tmp_path)
        try:
            src.backup(dest)
        finally:
            dest.close()
            src.close()
        raw_kb = os.path.getsize(tmp_path) // 1024
        with open(tmp_path, 'rb') as f_in, gzip.open(dest_path, 'wb', compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out, 1024 * 1024)
        os.remove(tmp_path)
        gz_kb = os.path.getsize(dest_path) // 1024
        print(f'[backup] ✓ {dest_path} ({gz_kb} KB, from {raw_kb} KB)', flush=True)
    except Exception as e:
        print(f'[backup] ✗ failed: {e}', flush=True)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)     # never leave a half-written copy eating the volume
        except Exception:
            pass
        return False

    _prune_backups()
    return True

def _run_daily_db_maintenance():
    """Daily housekeeping so the app stays fast as the database grows: prunes
    rows that have zero retention value once stale, then VACUUMs the database
    file to reclaim space and defragment it.

    Deliberately conservative about what gets pruned -- only tables with no
    user-facing or financial meaning once old:
      - group_typing: a live "is typing…" indicator, meaningless the moment
        it's stale, safe to clear entirely every time.
      - security_log: an audit trail read only as "last 20 rows" (admin
        panel) or "count in the last hour" (rate checks) -- a 180-day
        retention window is generous for either and never touched by those
        queries.
    Everything else (trades, fees, notifications, feed posts/replies,
    post_views, portfolio_snapshots) is left alone because it's either a
    financial record or something a user can actually see. agent_journal is
    also left alone even though it's an internal log -- _check_daily_spend
    -style risk checks read recent rows from it directly, so pruning it needs
    a deliberate retention decision, not a guess made here.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute('DELETE FROM group_typing')
        sec_cutoff_days = 180
        cur = conn.execute(
            "DELETE FROM security_log WHERE timestamp < datetime('now', ?)",
            (f'-{sec_cutoff_days} days',)
        )
        sec_pruned = cur.rowcount
        conn.commit()
        conn.close()
        print(f'[db-maintenance] cleared group_typing, pruned {sec_pruned} '
              f'security_log rows older than {sec_cutoff_days}d', flush=True)
    except Exception as e:
        print(f'[db-maintenance] prune error: {e}', flush=True)

    # Truncate the write-ahead log first. In WAL mode the -wal file grows
    # until a checkpoint retires it, and a passive checkpoint leaves the file
    # at its high-water mark -- so a busy day can leave hundreds of megabytes
    # of WAL sitting on the volume indefinitely. This is cheap, needs no
    # spare space, and is the one reclaim that always works.
    try:
        wal = DB_FILE + '-wal'
        wal_before = os.path.getsize(wal) if os.path.exists(wal) else 0
        wconn = sqlite3.connect(DB_FILE, isolation_level=None)
        try:
            wconn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        finally:
            wconn.close()
        wal_after = os.path.getsize(wal) if os.path.exists(wal) else 0
        if wal_before:
            print(f'[db-maintenance] WAL {wal_before // 1024}KB -> {wal_after // 1024}KB', flush=True)
    except Exception as e:
        print(f'[db-maintenance] WAL checkpoint error: {e}', flush=True)

    try:
        # VACUUM rebuilds the database into a temporary copy, so it needs
        # roughly the size of the database FREE on the same volume. Running it
        # on a nearly-full disk is how a space problem becomes an outage:
        # it fails, and it can fill what little is left while failing.
        size_before = os.path.getsize(DB_FILE)
        free = _free_bytes()
        if 0 <= free < size_before * 2:
            print(f'[db-maintenance] VACUUM skipped — needs ~{size_before * 2 // (1024*1024)} MB '
                  f'free, have {free // (1024*1024)} MB', flush=True)
        else:
            # A fresh connection in autocommit mode -- VACUUM can't run inside a
            # transaction, and needs exclusive access to rebuild the file.
            vconn = sqlite3.connect(DB_FILE, isolation_level=None)
            vconn.execute('VACUUM')
            vconn.close()
            size_after = os.path.getsize(DB_FILE)
            print(f'[db-maintenance] VACUUM done — {size_before // 1024}KB -> {size_after // 1024}KB', flush=True)
    except Exception as e:
        print(f'[db-maintenance] VACUUM error: {e}', flush=True)


def _start_backup_scheduler():
    if not _APSCHEDULER_OK:
        print('[backup] APScheduler not available — install apscheduler for scheduled backups', flush=True)
        # Fall back to a simple thread-based 60-second delay + no recurring schedule
        def _once():
            time.sleep(60)
            backup_database()
            _run_daily_db_maintenance()
        threading.Thread(target=_once, daemon=True).start()
        return
    try:
        _sched = _BgScheduler(timezone='UTC')
        # Daily at 03:00 UTC
        _sched.add_job(backup_database, _CronTrigger(hour=3, minute=0), id='daily_backup', replace_existing=True)
        # Daily at 03:30 UTC -- after that day's backup, before the 04:00 AI
        # self-analysis job reads the database.
        _sched.add_job(_run_daily_db_maintenance, _CronTrigger(hour=3, minute=30), id='daily_db_maintenance', replace_existing=True)
        # Hourly, on the hour
        _sched.add_job(_recover_uncollected_fees, _CronTrigger(minute=0), id='hourly_fee_recovery', replace_existing=True, kwargs={'triggered_by': 'scheduled'})
        # Hourly, on the hour
        _sched.add_job(_snapshot_portfolios, _CronTrigger(minute=0), id='hourly_portfolio_snapshot', replace_existing=True, kwargs={'triggered_by': 'scheduled'})
        # Daily at 04:00 UTC -- an hour after the DB backup, so it reads a
        # database that's already been safely snapshotted for the day.
        # Only ever produces a pending ai_filter_proposals row; see
        # run_ai_self_analysis()'s own docstring for why it never applies
        # itself.
        _sched.add_job(run_ai_self_analysis, _CronTrigger(hour=4, minute=0), id='daily_ai_self_analysis', replace_existing=True)
        # One-shot startup backup after 60 s
        run_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=60)
        _sched.add_job(backup_database, 'date', run_date=run_at, id='startup_backup')
        _sched.start()
        print('[backup] scheduler started — daily backup 03:00 UTC, daily DB maintenance 03:30 UTC, '
              'hourly fee recovery, hourly portfolio snapshot, daily AI self-analysis 04:00 UTC, startup in 60 s', flush=True)
    except Exception as e:
        print(f'[backup] scheduler error: {e}', flush=True)

_start_backup_scheduler()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print('OrcAgent Dashboard running on port', port)
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
