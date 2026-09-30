"""Token Launch: the fee tiles follow the chosen reward mode.

OrcAgent's 20% platform fee is a share of the CREATOR's fees, so it only
exists on Creator and Community launches: with Holder Rewards every creator
fee goes to the token's holders, the creator gets none, and OrcAgent takes
nothing (orc_bps is 0 for that mode, and nothing is added to the on-chain
fee-sharing config). The page still showed "Your earnings 80% of creator
fees" and "OrcAgent platform fee 20%" with Holder Rewards selected, and the
Community tiles/acknowledgement said 80% although the community's share
comes out of it. The tiles, the worked example and the acknowledgement now
follow the mode.
"""
import os, subprocess
ROOT = os.path.join(os.path.dirname(__file__), '..')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()
py = read('token_launch.py'); js = read('static', 'token-launch.js')
orc = py[py.index('def orc_bps(row):'):py.index('def shared(row):')]
check('server: OrcAgent takes no platform fee on Holder Rewards (orc_bps is 0 outside creator/community)',
      "if row['reward_mode'] not in ('creator','community'):return 0" in orc
      and "new_orc if mode in ('creator','community') else 0" in py)
fn = js[js.index('function renderFeeStrips(mode,bps){'):]
fn = fn[:fn.index('\n}\n')]
check('the page re-renders the fee tiles on every mode change', ' renderFeeStrips(mode,bps);' in js)
check('Holder Rewards: creator fees "All to token holders", platform fee "None on Holder Rewards"',
      "holder?'All to token holders'" in fn and "holder?'None on Holder Rewards'" in fn)
check('Community: your share is 100% minus platform fee minus the community share',
      "mine=10000-orcBps-(mode==='community'?bps:0)" in fn and "' of creator fees'" in fn)
check('the worked example only shows for Creator Rewards; the acknowledgement names the real split',
      "example.hidden=mode!=='creator'" in fn and 'OrcAgent takes no platform fee' in fn
      and "my community '+money(bps/100)" in fn)
r = subprocess.run(['node', '--check', os.path.join(ROOT, 'static', 'token-launch.js')], capture_output=True, text=True)
check('token-launch.js parses', r.returncode == 0)
raise SystemExit(0 if all(checks) else 1)
