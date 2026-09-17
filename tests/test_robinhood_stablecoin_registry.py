"""Robinhood cross-chain routes need USDG decimals before bridge math runs."""
import importlib
import os
import sys
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from trade_engine import registry as registry_module  # noqa: E402
from robinhood_stablecoin_registry import (          # noqa: E402
    ROBINHOOD_USDG,
    ROBINHOOD_USDG_DECIMALS,
    install,
)


R = importlib.reload(registry_module)
d = SimpleNamespace(te_registry=R)

before = R.get_chain('robinhood').stable
assert before.address.lower() == ROBINHOOD_USDG.lower()
assert before.decimals is None

install(d)

after = R.get_chain('robinhood').stable
assert after.decimals == ROBINHOOD_USDG_DECIMALS == 6
assert after.require_decimals() == 6
assert not any(a.address.lower() == ROBINHOOD_USDG.lower() for a in R.unverified_assets())

# Idempotent: app startup/reloader may install the adapter more than once.
install(d)
assert R.get_chain('robinhood').stable.decimals == 6

# The guard must fail closed if somebody later points Robinhood at another
# stablecoin but forgets to update this verified bootstrap.
original = R.CHAINS['robinhood']
try:
    bad = R.Asset('robinhood', '0x0000000000000000000000000000000000000001',
                  'USDG', None, 'stable')
    R.CHAINS['robinhood'] = R.Chain(
        original.name, original.kind, original.chain_id,
        original.native, bad, original.swap_provider, original.display_name,
    )
    try:
        install(d)
        raised = False
    except RuntimeError:
        raised = True
    assert raised
finally:
    R.CHAINS['robinhood'] = original

print('PASS Robinhood USDG metadata is resolved before cross-chain quoting')
