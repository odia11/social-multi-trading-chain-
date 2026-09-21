from pathlib import Path

js = Path('static/dashboard.js').read_text()
py = Path('dashboard.py').read_text()

checks = {
    'reposter banner remains separate': "reposterName+' reposted" in js,
    'repost card uses original user id': "user_id: orig.user_id || 0" in js,
    'repost card uses original username': "username: orig.username || orig.wallet || 'Trader'" in js,
    'repost card uses original full wallet': "wallet_full: orig.wallet_full || orig.wallet || ''" in js,
    'repost card uses original avatar': "avatar_url: orig.avatar_url || ''" in js,
    'backend original post includes user id': "'kind': 'p', 'user_id': r2[4] or 0" in py,
    'backend original post includes full wallet': "'wallet': _oshort, 'wallet_full': _ow" in py,
    'backend original trade includes user id': "'kind': 't', 'user_id': r2[1] or 0" in py,
}

for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL') + ': ' + name)
    if not ok:
        raise SystemExit(1)
print(f'{len(checks)}/{len(checks)} checks passed')
