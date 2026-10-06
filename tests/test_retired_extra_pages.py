"""Retired standalone community dashboards must stay out of the user-facing app."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
retired={
    '/invitations':('templates/invitations.html','static/invitations.js'),
    '/following':('templates/following.html','static/following.js','static/following.css'),
    '/watchlist':('templates/watchlist.html','static/watchlist.js'),
    '/rewards':('templates/rewards.html',),
}
for route,files in retired.items():
    for rel in files:
        assert not (ROOT/rel).exists(), rel+' should stay retired'

visible=[
    ROOT/'dashboard.py', ROOT/'templates/profile.html', ROOT/'templates/referrals.html',
    ROOT/'templates/live_market_pro.html', ROOT/'templates/info.html',
    ROOT/'static/app-ux.js', ROOT/'static/sw.js', ROOT/'platform_assistant.py',
]
for path in visible:
    text=path.read_text()
    for route in retired:
        assert ('href="'+route) not in text, (path,route)
        assert ("href='"+route) not in text, (path,route)
        assert ('https://orcagent.fun'+route) not in text, (path,route)

assert "('/rewards', 'Activity badges'" not in (ROOT/'dashboard.py').read_text()
assert "('/following','Following & alerts'" not in (ROOT/'following_traders.py').read_text()
assert "('/watchlist', 'Watchlist & alerts'" not in (ROOT/'watchlist_alerts.py').read_text()
assert "('/invitations','Invitations & shared calls'" not in (ROOT/'call_invitations.py').read_text()
for route in retired:
    assert ("'"+route+"',") not in (ROOT/'static/app-ux.js').read_text()
    assert ("'"+route+"',") not in (ROOT/'static/sw.js').read_text()
print('RETIRED_EXTRA_PAGES_CONTRACT_PASS')
