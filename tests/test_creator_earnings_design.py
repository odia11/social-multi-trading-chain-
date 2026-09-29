"""Visual/data contract for the OrcAgent Creator Earnings redesign."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'templates'/'token_launch.html').read_text()
JS=(ROOT/'static'/'token-launch.js').read_text()
CSS=(ROOT/'static'/'token-launch-redesign.css').read_text()

checks={
 'OrcAgent creator earnings header and private state':
   'Creator Earnings' in HTML and 'Earnings from tokens you created on OrcAgent.' in HTML and 'tl-private-chip' in HTML,
 'large real claimable balance and CTA':
   'id="tl-available-usdc"' in HTML and 'id="tl-claim-now"' in HTML and 'Available to claim' in HTML,
 'overview metrics preserve verified data':
   all(x in HTML for x in ('id="tl-claimed-usdc"','id="tl-claim-count"','id="tl-creator-share"')),
 'recent activity uses actual claim history':
   'id="tl-recent-earnings"' in HTML and ".slice(0,3)" in JS and "renderClaimRows($('tl-recent-earnings'),history.filter(" in JS,
 'global CTA reuses guarded existing claim flow':
   'creatorClaimLaunch()' in JS and 'claimRewards(launch)' in JS,
 'pending claim CTA opens history instead of preparing a duplicate':
   "btn.dataset.mode='history'" in JS and "if(this.dataset.mode==='history')" in JS,
 'available and claimed USD hints come from raw verified USDC':
   "rawNumber(creatorAvailableRaw,'USDC')" in JS and "rawNumber(claimedRaw,'USDC')" in JS,
 'new card system exists':
   '.tl-ce-available{' in CSS and '.tl-ce-metrics{' in CSS and '.tl-ce-recent{' in CSS,
 'user-facing launch UI has no third-party launch branding':
   not any(x in HTML or x in JS for x in ('Pump.fun','pump.fun','PumpSwap','Pump fees','Pump transaction')),
}
for label,ok in checks.items():
    print(('PASS' if ok else 'FAIL')+' - '+label)
    assert ok,label
print('ALL CREATOR EARNINGS DESIGN CONTRACTS PASSED')
