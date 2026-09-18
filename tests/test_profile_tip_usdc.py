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

# ── the sheet the design asked for ───────────────────────────────────────
_design = {
    'the amount shows what it is worth, which is the question a number in a '
    'box invites':
        'id="tip-approx"' in PROFILE and 'tip-send-usd' in PROFILE,
    'five presets, and the chosen one is marked':
        PROFILE.count('_tipPreset(') >= 2 and '.tip-preset.active' in PROFILE,
    'the button says what it will do, with the amount in it':
        'tip-submit-label' in PROFILE and "'Tip ' + (+a) + ' USDC'" in PROFILE,
    'the network is named, along with whose SOL pays the fee':
        'Solana (USDC)' in PROFILE and 'comes out of your own SOL' in PROFILE,
    'the optional note counts its characters against the limit it enforces':
        'maxlength="100"' in PROFILE and 'tip-count' in PROFILE,
    # A memo does not ride along on this transfer, so a message field that
    # only looked like it sent something would be decoration.
    'the note is delivered as a real message, and only AFTER the transfer '
    'is confirmed':
        "/api/messages/' + _tipPeerId" in PROFILE
        and PROFILE.index('_tipSendNote(amount)') > PROFILE.index('d && d.ok'),
    'a role badge only appears for a role that means something — everybody '
    'is a "user"':
        "not in ('user', 'member', 'none')" in PROFILE,
    'and it says once, plainly, that a tip cannot be taken back':
        'cannot be reversed' in PROFILE,
}
for label, ok in _design.items():
    print(('PASS' if ok else 'FAIL') + ' - ' + label)
    assert ok, label

# ── the action row must fit a phone ──────────────────────────────────────
# Five controls (Follow, Tip USDC, Message, notify, share) were in one row
# that static/profile-v2.css told never to wrap, with the text buttons on
# flex:1 and a zero basis. So they shrank to 59px, kept their padding, and
# printed "Following" and "Message" straight through their own borders.
# Measured in Chromium at 390px and 360px after the fix: two per line, no
# element wider than its content.
CSS = (Path(ROOT) / 'static' / 'profile-v2.css').read_text()
_row = {
    'the action row may wrap, because five controls do not fit one phone line':
        '.oa-profile-v2 .pf-action-row{display:flex;gap:8px;margin:0 0 18px;flex-wrap:wrap}' in CSS,
    'the text buttons have a real flex basis, so they wrap instead of '
    'shrinking below their own labels':
        'flex:1 1 132px' in CSS and 'flex:1' + ';' not in CSS.replace('flex:1 1', ''),
    'the tip button is sized by the same rule as the others, not by a '
    'special case in the template':
        '.oa-profile-v2 .pf-btn-tip{' in CSS or '.oa-profile-v2 .pf-btn-tip,' in CSS
        or ',.oa-profile-v2 .pf-btn-tip' in CSS,
    'and the template no longer sets its own width for that button — one '
    'layout, one owner':
        'pf-action-row .pf-btn-tip{flex' not in PROFILE,
}
for label, ok in _row.items():
    print(('PASS' if ok else 'FAIL') + ' - ' + label)
    assert ok, label
