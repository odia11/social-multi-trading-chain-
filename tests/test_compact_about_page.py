from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'templates'/'info.html').read_text()
assert 'Trade. Automate. Connect.' in HTML
assert 'OrcAgent brings <strong>Solana trading, automation and social features</strong> into one app.' in HTML
for heading in ('Trade','Automate','Social','Launch'):
    assert f'<h3>{heading}</h3>' in HTML
for retired in ('Trade it. Share it.','Start in three steps','One Portfolio','Messages</h3>'):
    assert retired not in HTML
assert HTML.count('about-card') >= 4
print('COMPACT_ABOUT_PAGE_PASS')
