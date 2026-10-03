"""Live Market must paint warm data before account/watchlist requests finish."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
D=(ROOT/'dashboard.py').read_text()
T=(ROOT/'templates/live_market_pro.html').read_text()
J=(ROOT/'static/live-market-pro.js').read_text()

checks=[]
def check(label,cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+label)

route=D[D.index("@app.route('/live-market')"):D.index("@app.route('/live-market/pro')")]
check('live-market route snapshots the warm scanner cache without refreshing upstream',
      "with _scanner_lock:" in route
      and "_scanner_cache.get('data')" in route
      and "_get_scanner_cached()" not in route)
check('route caps initial payload instead of bloating navigation HTML',
      "initial_market_tokens = cached_tokens[:30]" in route)
check('template embeds a JSON first-paint market payload',
      'id="pt-initial-feed"' in T and 'initial_market_tokens' in T)
check('client can hydrate from the embedded payload before network data arrives',
      'function hydrateInitialFeed()' in J
      and "document.getElementById('pt-initial-feed')" in J
      and 'renderFeedList();' in J[J.index('function hydrateInitialFeed()'):J.index('function patchWatchButtons()')])
check('a recent session market frame is a fallback for instant back-navigation',
      "_FEED_CACHE_KEY='orcaLiveMarketFeedV2'" in J
      and 'sessionStorage.setItem(_FEED_CACHE_KEY' in J
      and '300000' in J)
check('only the unfiltered default feed is persisted as the generic first frame',
      'function _defaultFeedState()' in J
      and "ST.sort==='trending'" in J)
check('scanner starts independently instead of waiting for watchlist',
      'loadFeed(_hydratedFeed);' in J
      and 'loadWatchlistSet().then(patchWatchButtons);' in J
      and "loadWatchlistSet().then(function(){ loadFeed(); });" not in J)
check('fresh scanner data replaces or patches the warm frame and refreshes its cache',
      'cacheDefaultFeed();' in J[J.index('function loadFeed(isPoll)'):J.index('/* ── trade actions')])
check('watchlist state patches buttons without rebuilding market cards',
      'function patchWatchButtons()' in J
      and "btn.classList.toggle('active',active)" in J)

raise SystemExit(0 if all(checks) else 1)
