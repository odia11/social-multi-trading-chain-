"""The gasless bootstrap and the bridge's own gate must agree on "enough SOL".

A wallet with 0.0014 SOL hit "Could not start automatic bridge from solana:
Insufficient SOL for network fees ... deposit a small amount of SOL first" --
even though solana_source_bridge_gasless.py exists specifically to avoid that
message by converting a slice of the user's own USDC into SOL first.

Reproduced live: the bootstrap module's "is a top-up even needed" check read
_execute_cross_chain_bridge()'s own SOL_BRIDGE_GAS_RESERVE via getattr(d,
'SOL_BRIDGE_GAS_RESERVE', 0.001) -- a default that only exists because the
real dashboard.py never defined the constant. dashboard.py's own hard gate,
meanwhile, was a separate hardcoded 0.002. A wallet holding between 0.001 and
0.002 SOL read as "already enough" to the bootstrap module, which skipped
straight to retrying the real bridge -- which immediately failed on the
*other* threshold with the exact same dead-end message the bootstrap exists
to avoid.

Fixed by giving both checks the one constant. This asserts they can't drift
apart again: dashboard.py must actually define SOL_BRIDGE_GAS_RESERVE (not
leave the gasless module's default silently in charge), the hard gate inside
_execute_cross_chain_bridge must read that same name rather than a literal
number, and the two values must be equal.
"""
import ast
import re
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(REPO + '/dashboard.py').read()
GASLESS = open(REPO + '/solana_source_bridge_gasless.py').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


check('dashboard.py defines a real SOL_BRIDGE_GAS_RESERVE constant, rather '
      "than leaving the gasless module's own fallback default silently in "
      "charge of the real gate",
      re.search(r'^SOL_BRIDGE_GAS_RESERVE\s*=\s*([0-9.]+)', SRC, re.M) is not None)

bridge = fn('_execute_cross_chain_bridge')
check("...and the bridge's own hard gate reads that constant, not a "
      'hardcoded number that can silently drift away from it',
      'SOL_BRIDGE_GAS_RESERVE' in bridge
      and not re.search(r'_origin_sol\s*<\s*0\.002', bridge))

dash_val = re.search(r'^SOL_BRIDGE_GAS_RESERVE\s*=\s*([0-9.]+)', SRC, re.M)
gasless_default = re.search(
    r"getattr\(d,\s*'SOL_BRIDGE_GAS_RESERVE',\s*([0-9.]+)\)", GASLESS)
check('the gasless bootstrap reads the SAME constant from the dashboard '
      'module (by name), so a future change to one moves the other',
      gasless_default is not None)
check("...and its own fallback default -- used only if the constant were "
      'ever removed -- is not silently lower than the real gate, which is '
      'exactly the gap that produced the dead zone',
      dash_val and gasless_default
      and float(gasless_default.group(1)) >= float(dash_val.group(1)))

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
