"""Regression checks for removing the legacy browser-visible shared secret."""
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, Response

ROOT = Path(__file__).resolve().parents[1]
ENTRY = (ROOT / 'app_entry.py').read_text(encoding='utf-8')
SRC = (ROOT / 'browser_shared_secret_hardening.py').read_text(encoding='utf-8')

checks = []
def check(name, ok):
    checks.append(bool(ok)); print(('PASS ' if ok else 'FAIL ') + name)

check('production entry installs browser shared-secret hardening',
      'browser_shared_secret_hardening' in ENTRY and '_install_browser_shared_secret_hardening(_dashboard)' in ENTRY)
check('legacy module shared secret is explicitly disabled',
      "dashboard_module.API_SHARED_SECRET = ''" in SRC)
check('app config shared secret is explicitly disabled',
      "app.config['API_SHARED_SECRET'] = ''" in SRC)
check('HTML safety net scrubs exact historical secret',
      'body.replace(legacy_secret' in SRC)
check('HTML scrub failure is fail-closed',
      'Security response blocked' in SRC and 'response.status_code = 500' in SRC)

# Exercise the adapter itself with a realistic page. This proves the original
# secret is absent even if a legacy renderer captured it before the module
# variable was blanked.
from browser_shared_secret_hardening import install
app = Flask(__name__)
secret = 'server-wide-value-that-must-never-reach-a-browser'
mod = SimpleNamespace(app=app, API_SHARED_SECRET=secret)

@app.get('/')
def home():
    return Response('<script>window.s="%s"</script>' % secret, mimetype='text/html')

install(mod)
with app.test_client() as client:
    r = client.get('/')
    body = r.get_data(as_text=True)
    check('runtime blanks dashboard API_SHARED_SECRET', mod.API_SHARED_SECRET == '')
    check('runtime blanks Flask API_SHARED_SECRET config', app.config.get('API_SHARED_SECRET') == '')
    check('historical server secret is absent from rendered HTML', secret not in body)
    check('scrubbed HTML is marked no-store', 'no-store' in (r.headers.get('Cache-Control') or ''))

raise SystemExit(0 if all(checks) else 1)
