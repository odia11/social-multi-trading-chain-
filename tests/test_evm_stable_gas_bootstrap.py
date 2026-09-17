"""Regression checks for user-funded EVM gas bootstrap."""
import os
import sys
from decimal import Decimal
from types import SimpleNamespace

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.chdir(REPO)

import evm_stable_gas_bootstrap as m

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

src = open(m.__file__).read()
check('native token uses the canonical 0x native-token sentinel',
      m._NATIVE_TOKEN == '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee')
check('bootstrap quote carries no OrcAgent platform-fee parameters',
      "'swapFeeRecipient'" not in src and "'swapFeeBps'" not in src and "'swapFeeToken'" not in src)
check('bootstrap never references a sponsor private key',
      'GAS_SPONSOR_PRIVATE_KEY' not in src)
check('confirmed gas is re-read from chain before success',
      'after_wei = int(w3.eth.get_balance(addr))' in src and 'after_wei >= need_wei' in src)
check('old ladder remains only as fallback',
      'return previous_ensure(' in src)

# ── the race this wrapper sits in front of ───────────────────────────────
# dashboard._get_evm_gas_lock exists because a live trade's pre-trade check
# and the background sweep in gas_manager.py can see the same stale low
# balance at the same time and each fire off their own top-up. The old ladder
# took that lock. A wrapper running in FRONT of it that does not would spend
# the user's stablecoin twice for gas they needed once.
check('the gasless attempt is serialized under the same per-(wallet, chain) '
      'lock the rest of the ladder uses',
      'with d._get_evm_gas_lock(wallet, chain):' in src)
check('...and the lock is released before the fallback, because that function '
      'takes the same lock and threading.Lock is not reentrant',
      src.index('with d._get_evm_gas_lock(wallet, chain):')
      < src.rindex('return previous_ensure(')
      and 'reentrant' in src)
check('...with the balance re-read INSIDE the lock, so a caller arriving '
      'right after a successful swap finds enough gas instead of buying more',
      src.index('with d._get_evm_gas_lock(wallet, chain):')
      < src.index('have_wei = int(w3.eth.get_balance(addr))'))

# Integration-order guarantee: app_entry installs this before bsc_gasless so
# the existing adapter captures this wrapper as its fallback.
entry = open(os.path.join(REPO, 'app_entry.py')).read()
bootstrap_at = entry.index('_install_evm_stable_gas_bootstrap(_dashboard)')
gasless_at = entry.index('_install_evm_gasless_trading(_dashboard)')
check('stable bootstrap installs before the EVM Gasless BUY adapter', bootstrap_at < gasless_at)
check('production still hard-disables platform gas fronting',
      "os.environ['ORCAGENT_FRONTS_GAS'] = '0'" in entry)

failed = [name for name, ok in checks if not ok]
print(f'\n{len(checks)-len(failed)}/{len(checks)} checks passed')
if failed:
    raise SystemExit(1)
