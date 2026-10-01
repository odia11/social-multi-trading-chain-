"""Portfolio -> Receive shows the EVM wallet too.

Every user has two deposit addresses: the Solana trading wallet and one
shared EVM wallet (the same 0x address on Base, BSC, Arbitrum and Robinhood
Chain). Receive only ever showed the Solana one, and the old deposit card
that had the EVM tab is hidden by the portfolio redesign -- so nobody could
find where to send USDC on an EVM chain. Receive now has a Solana / EVM
chains switch. The EVM side lists Base, BSC and Arbitrum with USDC: users
only ever deposit USDC, and Robinhood Chain (which has no USDC) is funded by
the app bridging it there.
"""
import os, sys, tempfile
ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, ROOT)
os.environ.update({'DATA_DIR': tempfile.mkdtemp(),
                   'ENCRYPTION_KEY': '6UorqYgQpSk59aqy_MY73E0nlUjevVeCj0clmTGE_Ck=',
                   'ORCAGENT_FRONTS_GAS': '0', 'ORCAGENT_POSITION_GUARDIAN': '0'})
import app_entry  # noqa: E402
d = app_entry._dashboard
from solders.keypair import Keypair  # noqa: E402

checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

html = open(os.path.join(ROOT, 'templates', 'wallet.html'), encoding='utf-8').read()
rx = html[html.index('// Two networks, one sheet.'):html.index('// Send used to mean "send SOL"')]
check('Receive has a Solana / EVM chains switch (only when the EVM wallet exists)',
      "onclick=\"_modalDeposit(\\'sol\\')\">Solana</button>" in rx
      and "onclick=\"_modalDeposit(\\'evm\\')\">EVM chains</button>" in rx and 'var tabs=_bscAddr' in rx)
check('...the EVM side shows the 0x address, its QR code, copy and share of THAT address',
      "function _rxAddr(){ return _rxNet==='evm'?_bscAddr:_walletAddr }" in rx
      and "_qrSvg(addr,'H')" in rx and "if(_rxNet==='evm') _copyAddrBsc(); else _copyAddr()" in rx
      and 'var addr=_rxAddr()' in rx[rx.index('function _rxShare('):])
check('...and an explorer that covers every EVM chain', "'https://blockscan.com/address/'" in rx)
check('the EVM side lists the chains a user deposits USDC on: Base, BSC, Arbitrum',
      "var _RX_EVM_CHAINS=['Base','BSC','Arbitrum']" in rx and 'Scan to send USDC on one of these chains' in rx)
check('...never USDG: Robinhood Chain is funded by the app bridging USDC (test_one_currency)',
      'USDG' not in rx.replace('// test_one_currency.py', '').split('var _RX_EVM_CHAINS')[1]
      and 'OrcAgent moves your USDC there automatically' in rx)
check('...and the warning says where to send and where not to',
      'Send <b>USDC</b> on Base, BSC or Arbitrum only' in rx and 'Never send from Solana or Ethereum to this address.' in rx)
check('the old deposit card no longer mentions Polygon', 'POL for Polygon' not in html)

w = str(Keypair().pubkey()); d.get_or_create_user(w)
c = app_entry.app.test_client()
with c.session_transaction(base_url='https://orcagent.fun') as s:
    s['wallet'] = w; s['csrf_token'] = 'x' * 30
page = c.get('/wallet', base_url='https://orcagent.fun')
body = page.get_data(as_text=True)
check('the Portfolio page renders with the user\'s EVM address available to Receive',
      page.status_code == 200 and 'var _bscAddr = "0x' in body)
raise SystemExit(0 if all(checks) else 1)
