"""The Live Market page loading should never wait on a live safety check.

/api/market/scanner runs a real mint/LP/honeypot check on every candidate
that isn't already cached, up to 12 in parallel -- and every page load
called it fresh, since only the individual check results were cached (10
min), not the fact that the whole batch had already been paid for. A newly-
trending token, or the first request after each 15s scanner-candidate
refresh, paid the full live cost synchronously, in the middle of a page
load -- exactly the "wachtmoment" this exists to remove.

_scanner_safety_warm_loop() (a background thread, started alongside
surge_radar's and gas_manager's own loops -- see the bottom of dashboard.py)
now runs that same check proactively, on every current scanner candidate,
before anyone asks. The request path in api_market_scanner is UNCHANGED --
still checks the cache first, still falls back to a live check on a genuine
miss -- so nothing about correctness or the fallback changed; a request
almost never needs that fallback any more, that's all.
"""
import ast
import re
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(REPO + '/dashboard.py', encoding='utf-8').read()
TREE = ast.parse(SRC)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


def fn(name):
    f = next(n for n in ast.walk(TREE)
             if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(SRC, f) or ''


warm = fn('_scanner_safety_warm_loop')
check('the warmer reuses the scanner\'s own cached candidate list, so it '
      'adds no extra upstream (DexScreener) load of its own',
      '_get_scanner_cached()' in warm)
check('...and pre-fills the SAME cache api_market_scanner reads from '
      '(_scanner_get_safety), not a second, disconnected one',
      '_scanner_get_safety(' in warm)
check('both include_lp variants are warmed -- a request with the LP-locked '
      'filter on is a different cache key (see _scanner_get_safety) and '
      'would otherwise still pay the live cost this exists to avoid',
      re.search(r'\(mint,\s*chain,\s*False\)', warm) is not None
      and re.search(r'\(mint,\s*chain,\s*True\)', warm) is not None)
check('checks run in parallel, same as the request-path fallback already '
      'does, so a cold cycle (server just started) still finishes in one '
      'round rather than one-at-a-time',
      'ThreadPoolExecutor' in warm)
check('one bad cycle (a scanner-candidate read failure, a check that '
      'raises) cannot kill the loop -- it is a background thread with no '
      'one waiting on it, and a crashed loop silently stops warming '
      'anything ever again',
      'except Exception' in warm and 'while True' in warm)

check('the warmer thread is actually started at boot, alongside every '
      'other background loop (surge_radar, gas_manager, ...)',
      'threading.Thread(target=_scanner_safety_warm_loop, daemon=True).start()' in SRC)

# ── the request path itself must be untouched ───────────────────────────────
scanner_route = SRC[SRC.index("def api_market_scanner("):SRC.index('\ndef ', SRC.index("def api_market_scanner(") + 10)]
check('api_market_scanner still checks the cache first and still has its '
      'own live fallback for a genuine miss -- this fix does not remove '
      'correctness, it just makes the fallback rare',
      'ThreadPoolExecutor' in scanner_route and '_scanner_get_safety(' in scanner_route)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
