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

# ── the page has to be a PAGE ────────────────────────────────────────────
# The first attempt at this feature replaced the 975-line redesigned profile
# with a 238-line fragment that stopped mid-CSS: no </style>, no body, no tip
# button, nothing. It rendered as a blank page and this file's own first
# check failed. So: assert the document is whole, and that the redesign it
# was written against is still the one being edited.
_whole = {
    'the document is complete, not truncated mid-style':
        PROFILE.count('</style>') >= 1 and PROFILE.rstrip().endswith('</html>'),
    'the redesigned profile is what the tip sits on, not an older copy':
        'profile-v2.css' in PROFILE,
    'the page a visitor sees is still there: follow, message, the stats':
        'pf-follow-btn' in PROFILE and '/messages/' in PROFILE,
    'the tip sheet cannot be redirected — the recipient is rendered by the '
    'server and there is no recipient field to type into':
        'id="tip-amount"' in PROFILE and 'name="to_address"' not in PROFILE,
    'the tip is sent with the CSRF token, like every other mutating call':
        "'X-CSRF-Token':_csrf" in PROFILE,
    'a lost connection does not invite a second transfer':
        'check your wallet before sending again' in PROFILE,
}
for label, ok in _whole.items():
    print(('PASS' if ok else 'FAIL') + ' - ' + label)
    assert ok, label
