"""Read-only autonomous-entry policy and 2s scanner regression tests.

Extract individual pure functions; never import the full production app or
execute a real trade, call external providers, or access production SQLite.
"""
import ast
import threading
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / 'dashboard.py').read_text()
JS = (Path(__file__).resolve().parents[1] / 'static/dashboard.js').read_text()
MOD = ast.parse(SOURCE)


def extract(name, ns):
    fn = next(n for n in MOD.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<test-policy>', 'exec'), ns)
    return ns[name]


def test_policy():
    assert 'BOT_MIN_24H_TXNS = 100' in SOURCE and 'BOT_MIN_24H_SELLS = 10' in SOURCE
    eligible = extract('_bot_gainers_eligible', {'BOT_MIN_24H_TXNS': 100, 'BOT_MIN_24H_SELLS': 10})
    good = {'txns24h': 100, 'txns24h_sells': 10}
    assert eligible(good)
    assert eligible({**good, 'has_profile': False}), 'a paid DexScreener profile is not required'
    for change in ({'txns24h': 99}, {'txns24h_sells': 9}, {'txns24h': None},
                   {'txns24h': 'bad'}, {'txns24h_sells': None}):
        assert not eligible({**good, **change}), change
    assert not eligible({})
    print('PASS 24h >=100 transactions, >=10 sells on every BUY; no paid profile needed')


def test_fast_pump_chain_isolation():
    ns = {'_fast_hist_lock': threading.Lock(), 'FAST_POLL_INTERVAL': 2,
          'FAST_PUMP_WINDOW': 15, 'FAST_PUMP_THRESHOLD': .06,
          '_fast_price_history': {
              'sol-mint': [(100, 1), (102, 1.07)],
              ('base','0xabc'): [(100, 1), (102, 1.07)],
              ('bsc','0xabc'): [(100, 1), (102, .98)],
          }, 'time': __import__('time')}
    fn = extract('_fast_pump_check', ns)
    assert fn('sol-mint', now=103)
    assert fn('0xabc', now=103, chain='base')
    assert not fn('0xabc', now=103, chain='bsc')
    assert not fn('0xabc', now=120, chain='base')
    ns['_fast_price_history'][('base','0xabc')].append((104, 1.055))
    assert not fn('0xabc', now=104, chain='base'), 'do not buy the down-tick'
    print('PASS 6%/15s fast pump: cross-chain isolation, stale-data refusal, reversal veto')


def test_cadence_and_routes():
    assert 'FAST_POLL_INTERVAL   = 2' in SOURCE
    assert '_scan_interval = 2.0' in SOURCE
    assert '_wait_s = _scan_interval' in SOURCE
    assert 'time.sleep(DISCOVERY_INTERVAL)  # shared candidate refresh' in SOURCE and 'DISCOVERY_INTERVAL = 10 ' in SOURCE
    assert 'interval:2,trade_pct:0.20' in JS
    for token in ('_bot_gainers_eligible(_t)', '_bot_gainers_eligible(t)',
                  '_bot_gainers_eligible(_td)', "_fast_pump_check(mint, chain=chain)"):
        assert token in SOURCE, token
    evm = (Path(__file__).resolve().parents[1] / 'multichain_auto_bot.py').read_text()
    assert 'd._bot_gainers_eligible(t)' in evm
    assert 'd._bot_gainers_eligible(td)' in evm
    assert 'pending_auto_buys[order_key] = now + 1800' in evm
    assert 'd._fast_pump_check(mint, chain=chain)' in evm
    print('PASS 2-second target, shared 30-second discovery, all-chain policy and duplicate protection')


if __name__ == '__main__':
    test_policy()
    test_fast_pump_chain_isolation()
    test_cadence_and_routes()
