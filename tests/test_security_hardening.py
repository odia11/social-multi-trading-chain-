#!/usr/bin/env python3
"""Static regression checks for OrcAgent's production security layer.

These checks deliberately avoid importing dashboard.py so they are fast and do
not need production environment variables. They protect the security adapter
from being accidentally removed or weakened by later UI/deploy work.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HARDENING = (ROOT / 'security_hardening.py').read_text(encoding='utf-8')
RUNTIME = (ROOT / 'static' / 'security-runtime.js').read_text(encoding='utf-8')
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')

failures = []


def check(name, condition):
    if condition:
        print('OK  ', name)
    else:
        print('FAIL', name)
        failures.append(name)


check('production entry imports the security installer',
      'from security_hardening import install as _install_security_hardening' in ENTRY)
check('production entry installs the security layer',
      '_install_security_hardening(_dashboard)' in ENTRY)

check('TRACE and CONNECT are explicitly blocked',
      "_BLOCKED_METHODS = frozenset({'TRACE', 'CONNECT'})" in HARDENING
      and 'method in _BLOCKED_METHODS' in HARDENING)
check('Fetch Metadata blocks cross-site state changes',
      "Sec-Fetch-Site" in HARDENING and "fetch_site == 'cross-site'" in HARDENING)
check('request body size is bounded', "MAX_CONTENT_LENGTH" in HARDENING)
check('session cookies are HttpOnly', "SESSION_COOKIE_HTTPONLY'] = True" in HARDENING)
check('session cookies require HTTPS', "SESSION_COOKIE_SECURE'] = True" in HARDENING)
check('session cookies use SameSite', "SESSION_COOKIE_SAMESITE'] = 'Lax'" in HARDENING)
check('CSP disables object content', '"object-src \'none\'"' in HARDENING)
check('CSP prevents third-party framing', '"frame-ancestors \'none\'"' in HARDENING)
check('CSP explicitly permits only the required Dexscreener frame',
      '"frame-src \'self\' https://dexscreener.com"' in HARDENING)
check('CSP script elements require a per-response nonce',
      'script-src-elem' in HARDENING and "'nonce-{nonce}'" in HARDENING)
check('HSTS is sent', 'Strict-Transport-Security' in HARDENING)
check('MIME sniffing is disabled', 'X-Content-Type-Options' in HARDENING and 'nosniff' in HARDENING)
check('legacy framing is denied', 'X-Frame-Options' in HARDENING and 'DENY' in HARDENING)
check('cross-origin opener isolation is enabled', 'Cross-Origin-Opener-Policy' in HARDENING)
check('security runtime is injected in HTML',
      'security-runtime.js?v=3' in HARDENING and 'data-orca-security-runtime' in HARDENING)

check('runtime blocks javascript URLs', "javascript:" in RUNTIME)
check('runtime blocks vbscript URLs', "vbscript:" in RUNTIME)
check('runtime rejects active data content while allowing raster images',
      'data:image\\/(?:png|jpe?g|webp|gif)' in RUNTIME and "low.indexOf('data:')" in RUNTIME)
check('runtime strips iframe srcdoc', "hasAttribute('srcdoc')" in RUNTIME and "removeAttribute('srcdoc')" in RUNTIME)
check('runtime observes dangerous attribute mutations',
      'attributes:true' in RUNTIME and "attributeFilter:['href','src','action','formaction','srcdoc']" in RUNTIME)
check('copy modal renders usernames as text, not interpolated HTML',
      'strong.textContent=String(username' in RUNTIME
      and 'strong2.textContent=String(username' in RUNTIME
      and 'document.createTextNode' in RUNTIME)
check('same-origin API URL fields are normalized before legacy HTML rendering',
      'sanitizeApiJson' in RUNTIME and "u.pathname.indexOf('/api/')" in RUNTIME
      and "lk==='url'||lk==='href'||/_url$/" in RUNTIME)
check('window.open is guarded against active URL schemes',
      'installWindowOpenGuard' in RUNTIME and 'original.call(window' in RUNTIME)

if failures:
    print('\n%d security regression check(s) failed.' % len(failures))
    sys.exit(1)
print('\nAll security hardening regression checks passed.')
