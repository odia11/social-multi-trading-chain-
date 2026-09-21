"""Regression guards for Live Market request coalescing/backoff."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DASH=(ROOT/'dashboard.py').read_text()
JS=(ROOT/'static'/'live-market-pro.js').read_text()


def test_page_uses_one_multichain_price_request():
    block=JS[JS.index('function tickLivePrices()'):JS.index('function startLivePrices()')]
    assert "/api/market/prices-batch?" in block
    assert "/api/market/prices?chain=" not in block
    assert "qs.set('groups',JSON.stringify(groups))" in block


def test_price_poll_never_overlaps_and_backs_off():
    block=JS[JS.index('var _priceTimer = null;'):JS.index('// `chain` defaults to')]
    assert '_priceInFlight' in block
    assert 'Date.now()<_priceNextAt' in block
    assert 'r.status===429||r.status===503' in block
    assert 'Math.min(8000' in block
    assert '_priceInFlight=false' in block


def test_hidden_tabs_do_not_poll_market_panels():
    tail=JS[JS.rindex('setInterval(function(){ if(!document.hidden) loadFeed(true);')-200:]
    assert 'if(!document.hidden) loadFeed(true)' in tail
    assert 'if(!document.hidden) loadSurges()' in tail
    assert 'if(!document.hidden) loadTape()' in tail
    assert 'if(!document.hidden) loadTraders()' in tail
    assert 'if(!document.hidden) loadPulse()' in tail


def test_server_batch_route_is_bounded_and_parallel():
    block=DASH[DASH.index("@app.route('/api/market/prices-batch')"):DASH.index("@app.route('/api/chart/<mint>')")]
    assert '@rate_limit(90, 60)' in block
    assert 'room = max(0, 60 - total)' in block
    assert 'ThreadPoolExecutor' in block
    assert '_market_prices_for_pairs' in block


def test_single_chain_route_reuses_same_price_cache_helper():
    block=DASH[DASH.index("@app.route('/api/market/prices')"):DASH.index("@app.route('/api/market/prices-batch')")]
    assert '_market_prices_for_pairs(chain, wanted)' in block


if __name__=='__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS',name)
    print('ALL LIVE MARKET PRICE BATCH REGRESSIONS PASSED')
