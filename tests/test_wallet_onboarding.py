"""Production wiring and offline dependencies for the current wallet onboarding."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_uses_new_accounts_not_legacy_key_upload():
    entry = (ROOT / 'app_entry.py').read_text()
    assert '_install_new_wallet_accounts(_dashboard)' in entry
    assert '_install_wallet_onboarding(_dashboard)' not in entry


def test_wallet_crypto_is_vendored_and_loaded_without_cdn():
    html = (ROOT / 'dashboard.html').read_text()
    assert '/static/vendor/tweetnacl-1.0.3.min.js' in html
    assert 'unpkg.com/tweetnacl' not in html
    assert (ROOT / 'static/vendor/tweetnacl-1.0.3.min.js').stat().st_size > 30000
    assert (ROOT / 'static/vendor/tweetnacl-LICENSE.txt').exists()
