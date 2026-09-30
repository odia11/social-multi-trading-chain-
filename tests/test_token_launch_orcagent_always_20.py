"""Token Launch: OrcAgent always earns its 20% of a new launch's creator fees.

pump.fun's Holder Rewards make a holders PDA the coin's creator, so every
creator fee goes to holders and no fee-sharing config (OrcAgent's 20%) can
exist: a Holder Rewards launch paid OrcAgent nothing. Holder Rewards is no
longer offered: the form has no such option, the server refuses the mode,
an old holder draft cannot be built, and the pump adapter refuses it too.
OrcAgent's fee wallet is a fixed, valid address, so a public launch always
carries the share. The fee tiles show the real split for Creator and Community.
"""
import os, re, subprocess
ROOT = os.path.join(os.path.dirname(__file__), '..')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)
read = lambda *p: open(os.path.join(ROOT, *p), encoding='utf-8').read()
py = read('token_launch.py'); js = read('static', 'token-launch.js')
html = read('templates', 'token_launch.html'); adapter = read('pump_adapter', 'build-launch.cjs')

check('OrcAgent platform fee stays 20% of creator fees',
      "os.environ.get('ORCAGENT_CREATOR_FEE_BPS','2000')" in py)
check('new launches may only choose Creator or Community', "_MODES={'creator','community'}" in py)
check('an old Holder Rewards draft cannot be built',
      "if stage=='create' and row['reward_mode'] not in _MODES:" in py)
check('the page reports Holder Rewards as unavailable', "'holder':False" in py)
check('the launch form offers no Holder Rewards option', 'value="holder"' not in html)
check('the pump adapter refuses anything but Creator or Community and never sets holderReward',
      "if(!['creator','community'].includes(data.reward_mode))throw Error('Unsupported reward mode');" in adapter
      and 'const holderReward = false;' in adapter)
dash = read('dashboard.py')
fee = re.search(r"^FEE_WALLET\s*=\s*'([^']*)'", dash, re.M)
check('OrcAgent\'s fee wallet is a fixed, valid Solana address, so public launches always carry the 20%',
      fee and re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}', fee.group(1))
      and "return getattr(d,'FEE_WALLET','')" in py)
fn = js[js.index('function renderFeeStrips(mode,bps){'):]
fn = fn[:fn.index('\n}\n')]
check('the page re-renders the fee tiles on every mode change', ' renderFeeStrips(mode,bps);' in js)
check('the fee tiles never say OrcAgent takes nothing',
      'holder' not in fn and 'None on Holder Rewards' not in js and 'no platform fee' not in fn)
check('Community: your share is 100% minus platform fee minus the community share',
      "mine=10000-orcBps-(mode==='community'?bps:0)" in fn and "' of creator fees'" in fn)
check('the worked example only shows for Creator Rewards; the acknowledgement names the real split',
      "example.hidden=mode!=='creator'" in fn and "my community '+money(bps/100)" in fn)
r = subprocess.run(['node', '--check', os.path.join(ROOT, 'static', 'token-launch.js')], capture_output=True, text=True)
check('token-launch.js parses', r.returncode == 0)
raise SystemExit(0 if all(checks) else 1)
