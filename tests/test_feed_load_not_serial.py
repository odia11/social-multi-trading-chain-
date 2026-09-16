"""The feed's own network request must not wait on an unrelated one first.

loadWatchlistSet().then(function(){ loadFeed(); }) meant the scanner request
-- the one everyone is actually staring at a "Loading..." placeholder for --
could not even START until /api/watchlist had round-tripped, even though the
two have no real dependency: watchSet is only read at RENDER time (inside
cardHtml(), for each card's star), not needed to make the request at all.
That serial chain added a full extra network round trip to every single
Live Market page load, on top of whatever the scanner request itself takes.
"""
import re
import sys

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = open(REPO + '/static/live-market-pro.js', encoding='utf-8').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


check('loadWatchlistSet() and loadFeed() are no longer chained -- the feed '
      "request does not wait on the watchlist's round trip before it can "
      'even start',
      'loadWatchlistSet().then(function(){ loadFeed(); })' not in JS)
check('...both are still actually called on page load, just independently',
      re.search(r'loadWatchlistSet\(\);\s*\n\s*loadFeed\(\);', JS) is not None)

passed = sum(1 for _, ok in checks if ok)
print(f'\n{passed}/{len(checks)} checks passed')
sys.exit(0 if passed == len(checks) else 1)
