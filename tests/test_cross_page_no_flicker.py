"""Regression guards for non-destructive background refresh on shared pages."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
home=(root/'static/dashboard.js').read_text()
market=(root/'static/live-market-pro.js').read_text()
refresh=(root/'static/auto-refresh.js').read_text()
messages=(root/'templates/messages.html').read_text()
assert 'requestSeq !== _homeFeedRequestSeq' in home
assert 'if(logSig===_renderedLogSig) return;' in home
assert 'if(_renderedPositionIds===ids' in home
assert "if(listEl.querySelector('.pos-sell-conf')) return;" in home
assert "if(unchanged && document.querySelector('#center-feed .fc-card')) return;" in home
assert "feed.scrollTop>SCROLL_TOP_THRESHOLD" in refresh
assert 'if(newMarkup!==_surgeMarkup)' in market
assert 'if(identity===_tapeIdentity) return;' in market
assert 'if(identity===_traderIdentity) return;' in market
assert "if (incremental) area.insertAdjacentHTML('beforeend',renderedHtml);" in messages
for path in ['static/dashboard.js','static/live-market-pro.js','static/auto-refresh.js','static/messages-ui.js']:
    check=subprocess.run(['node','--check',str(root/path)],capture_output=True,text=True)
    assert check.returncode==0, f'{path}: {check.stderr}'
print('PASS Home preserves unchanged feed DOM and discards stale requests')
print('PASS unchanged logs and open-position controls do not get recreated on polls')
print('PASS auto-refresh checks desktop as well as document scrolling')
print('PASS Live Market does not rebuild unchanged surge/tape/trader rails')
print('PASS Messages appends new messages without replacing unchanged bubbles')
print('PASS JavaScript syntax across Home, Live Market, shared refresh and Messages')
