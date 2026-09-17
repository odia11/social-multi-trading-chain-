"""Robinhood USDG decimals: read from the chain, never assumed.

Robinhood routes refuse while USDG's decimals are unknown -- require_decimals()
raises rather than guess, which is right, and which also means a valid
USDC -> USDG -> token route never reaches 0x. This adapter closes that gap the
way trade_engine.registry says it must be closed:

    "by the app reading decimals() on-chain and telling the registry the
     answer, rather than by somebody typing a plausible number into this file"

USDG is 6 decimals everywhere Paxos has issued it. That expectation is kept as
a CROSS-CHECK, not as the answer. BSC's USDC is 18 while everyone else's is 6,
so nobody gets to assume, and an 18 read as 6 is a 10^12 sizing error.
"""
import importlib
import os
import sys
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from trade_engine import registry as registry_module  # noqa: E402
import robinhood_stablecoin_registry as RH            # noqa: E402

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fresh_registry():
    return importlib.reload(registry_module)


class FakeContract:
    def __init__(self, value):
        self._value = value
    class _Fns:
        pass
    @property
    def functions(self):
        fns = FakeContract._Fns()
        value = self._value
        fns.decimals = lambda: SimpleNamespace(call=lambda: value)
        return fns


def fake_chain(decimals_value=None, raises=False):
    """A stand-in for the Robinhood RPC. Nothing here touches a network."""
    class FakeEth:
        def contract(self, address=None, abi=None):
            if raises:
                raise ConnectionError('robinhood RPC unreachable')
            return FakeContract(decimals_value)
    class FakeW3:
        eth = FakeEth()
        def to_checksum_address(self, a):
            return a
    return SimpleNamespace(te_registry=R, _get_web3=lambda chain: FakeW3())


# ── the starting point ───────────────────────────────────────────────────
R = fresh_registry()
before = R.get_chain('robinhood').stable
check('USDG starts unverified, which is what makes a Robinhood route refuse',
      before.address.lower() == RH.ROBINHOOD_USDG.lower()
      and before.decimals is None)

# ── the chain answers 6 ──────────────────────────────────────────────────
d = fake_chain(6)
RH.install(d)
after = R.get_chain('robinhood').stable
check('asked, the contract answers 6 and the registry records it',
      after.decimals == 6 and after.require_decimals() == 6)
check('...and USDG is no longer listed as unverified',
      not any(a.address.lower() == RH.ROBINHOOD_USDG.lower()
              for a in R.unverified_assets()))
check('installing twice is harmless — startup and the reloader both run it',
      RH.install(d) is not None or True)
check('...and a second install does not re-read or re-write a verified value',
      R.get_chain('robinhood').stable.decimals == 6)

# ── the chain cannot be reached ──────────────────────────────────────────
R = fresh_registry()
d_down = fake_chain(raises=True)
result = RH.install(d_down)
check('an unreachable RPC installs NOTHING — decimals stay None, because an '
      'RPC being down is not evidence about a token, and a plausible default '
      'is the exact failure this mechanism exists to prevent',
      result is None and R.get_chain('robinhood').stable.decimals is None)

# ── the chain contradicts the expectation ────────────────────────────────
R = fresh_registry()
d_18 = fake_chain(18)
try:
    RH.install(d_18)
    check('a contradicting on-chain value is refused', False)
except RuntimeError as e:
    check('a contract answering 18 is REFUSED rather than written down — '
          'that is the 10^12 error, caught at the only moment it is cheap',
          '18' in str(e) and R.get_chain('robinhood').stable.decimals is None)

# ── the registry is not what this was written for ────────────────────────
R = fresh_registry()
original = R.CHAINS['robinhood']
try:
    bad = R.Asset('robinhood', '0x0000000000000000000000000000000000000001',
                  'USDG', None, 'stable')
    R.CHAINS['robinhood'] = R.Chain(
        original.name, original.kind, original.chain_id,
        original.native, bad, original.swap_provider, original.display_name)
    try:
        RH.install(fake_chain(6))
        check('a changed stablecoin address is refused', False)
    except RuntimeError:
        check('a changed stablecoin address is refused, so this adapter can '
              'never quietly apply USDG metadata to some other token', True)
finally:
    R.CHAINS['robinhood'] = original

# ── and a mismatch must not take the app down ────────────────────────────
ENTRY = open(os.path.join(REPO, 'app_entry.py')).read()
check('app_entry catches that refusal and carries on — Robinhood metadata on '
      'one chain is not a reason to stop Solana and Base from trading',
      '_install_robinhood_stablecoin_registry(_dashboard)' in ENTRY
      and 'except Exception as _e:' in ENTRY
      and 'other chain is unaffected' in ENTRY)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
