"""Regression checks for user-funded EVM gas bootstrap."""
from decimal import Decimal
from types import SimpleNamespace

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

# Integration-order guarantee: app_entry installs this before bsc_gasless so
# the existing adapter captures this wrapper as its fallback.
entry = open('app_entry.py').read()
bootstrap_at = entry.index('_install_evm_stable_gas_bootstrap(_dashboard)')
gasless_at = entry.index('_install_evm_gasless_trading(_dashboard)')
check('stable bootstrap installs before the EVM Gasless BUY adapter', bootstrap_at < gasless_at)
check('production still hard-disables platform gas fronting',
      "os.environ['ORCAGENT_FRONTS_GAS'] = '0'" in entry)

failed = [name for name, ok in checks if not ok]
print(f'\n{len(checks)-len(failed)}/{len(checks)} checks passed')
if failed:
    raise SystemExit(1)
