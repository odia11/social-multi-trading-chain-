from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = (ROOT / 'templates' / 'profile.html').read_text()
WITHDRAW = (ROOT / 'portfolio_token_withdraw.py').read_text()

checks = {
    'tip button is visible on another user profile': 'Tip USDC' in PROFILE and 'pf-btn-tip' in PROFILE,
    'tip uses existing authenticated token-send endpoint': "fetch('/api/wallet/send-token'" in PROFILE,
    'tip is fixed to canonical Solana USDC mint': "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" in PROFILE,
    'tip recipient is the profile wallet, not typed input': 'var _tipRecipient = {{ wallet|tojson }};' in PROFILE and "to_address:_tipRecipient" in PROFILE,
    'default OrcAgent banner is shown when user banner is absent': "{% set _default_banner = '/static/orcagent-mobile-hero.svg' %}" in PROFILE and "banner_url or _default_banner" in PROFILE,
    'default OrcAgent avatar is shown when avatar is absent': '/static/icon-180.png?v=6' in PROFILE,
    'backend remains authenticated and csrf protected': "wallet = d._authenticated_wallet()" in WITHDRAW and "if not _csrf_ok(d):" in WITHDRAW,
    'backend retains duplicate transfer protection': 'This token transfer was already submitted recently' in WITHDRAW,
}

for label, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ' - ' + label)
    assert ok, label
