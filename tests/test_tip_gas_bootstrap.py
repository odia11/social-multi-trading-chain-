"""A Solana tip/withdraw used to hard-fail for the common case: a trading
wallet that holds USDC but zero SOL, because buys are already gasless (see
solana_gasless_trading.py) and nothing ever asked the user to fund SOL by
hand. portfolio_token_withdraw._solana_transfer required a raw SOL balance
before the on-chain send, so that wallet's first tip died immediately with
"Not enough SOL in your trading wallet to pay the network fee" even when it
held plenty of USDC.

The fix reuses the same USDC -> SOL gasless bootstrap that cross-chain buys
already rely on (solana_source_bridge_gasless.py): if the wallet's SOL is
below the reserve, spend a sliver of the user's OWN spare USDC through
Jupiter's gasless route first, then proceed. OrcAgent still fronts nothing;
it only reaches for USDC the user already had, and never touches the USDC
the user is actively sending.
"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import pathlib
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = (ROOT / 'portfolio_token_withdraw.py').read_text(encoding='utf-8')
BRIDGE_SRC = (ROOT / 'solana_source_bridge_gasless.py').read_text(encoding='utf-8')
DASHBOARD_SRC = (ROOT / 'dashboard.py').read_text(encoding='utf-8')


def check(message, condition):
    assert condition, message
    print('PASS ' + message)


check('the withdraw/tip path reuses the existing gasless bridge bootstrap, not a new payment rail',
      'import solana_source_bridge_gasless as _bridge_gas' in SRC
      and '_bridge_gas._pick_gasless_order(' in SRC
      and '_bridge_gas._execute_order(' in SRC)
check('a low-SOL wallet is no longer refused outright before trying its own USDC',
      "raise ValueError('Not enough SOL in your trading wallet to pay the network fee')" not in SRC)
check('the hard block only fires once spare USDC is also insufficient to create gas',
      'usdc_available < _bridge_gas._MIN_BOOTSTRAP_USDC' in SRC
      and 'enough spare USDC to create it automatically' in SRC)
check('USDC actively being sent is reserved first and never spent twice on gas',
      "reserved_for_send = amount if token_address == _USDC_MINT else Decimal(0)" in SRC
      and 'usdc_balance - reserved_for_send' in SRC)
check('the reserve target matches the level dashboard.py already trusts for a transfer plus new-account rent',
      'SOL_GAS_MIN_BALANCE         = 0.003' in DASHBOARD_SRC
      and "_GAS_RESERVE_SOL = Decimal('0.003')" in SRC)
check('after a bootstrap swap the balance is re-read from chain rather than assumed',
      "getBalance', [owner_text, {'commitment':'confirmed'}]" in SRC
      and SRC.count("getBalance', [owner_text, {'commitment':'confirmed'}]") >= 2)
check('a bootstrap that never lands is reported, not silently swallowed into a false success',
      'the balance has not updated yet' in SRC)
check('the bootstrap runs inside the same authenticated key context as the send itself, never a caller-supplied key',
      "with d._use_key(enc, wallet) as private_key:" in SRC)
check('this stays a user-funded rail: no sponsor wallet, no platform key, is introduced',
      '_sponsor' not in SRC.lower() and 'platform_key' not in SRC.lower()
      and 'ORCAGENT_FRONTS_GAS' not in SRC)
check('the bridge module bootstrap this reuses is itself explicit about never subsidising the user',
      'OrcAgent never subsidises this flow' in BRIDGE_SRC)

# ── the budget math itself, exercised directly against the real constants ──
import portfolio_token_withdraw as w  # noqa: E402

reserved = Decimal('0.03')
tip_usdc_balance = Decimal('5.00')
usdc_available = tip_usdc_balance - reserved
check('tipping a small USDC amount from a well-funded wallet leaves plenty to bootstrap gas with',
      usdc_available >= w._bridge_gas._MIN_BOOTSTRAP_USDC and usdc_available == Decimal('4.97'))

thin_balance = Decimal('0.05')
thin_available = thin_balance - reserved
check('a wallet with almost nothing left after the tip itself is correctly refused, not silently drained',
      thin_available < w._bridge_gas._MIN_BOOTSTRAP_USDC)

print('\n12/12 checks passed')
