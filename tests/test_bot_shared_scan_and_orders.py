"""Side-effect-free regression checks for shared scans, per-position TP/SL, and order races."""
import ast
import concurrent.futures
import threading
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_multichain_auto_bot_gasless import make_dashboard
import multichain_auto_bot

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'dashboard.py').read_text()
MODULE = ast.parse(SOURCE)


def test_personal_tp_sl():
    names = ('_pos_tp_frac', '_pos_sl_frac')
    ns = {}
    for name in names:
        node = next(x for x in MODULE.body if isinstance(x, ast.FunctionDef) and x.name == name)
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<risk>', 'exec'), ns)
    assert ns['_pos_tp_frac']({'tp_pct': 20}, .50) == .20
    assert ns['_pos_tp_frac']({'tp_pct': 50}, .20) == .50
    assert ns['_pos_sl_frac']({'sl_pct': 5}, .10) == .05
    assert ns['_pos_sl_frac']({'sl_pct': 10}, .05) == .10
    assert ns['_pos_tp_frac']({}, .50) == .50
    assert ns['_pos_sl_frac']({}, .05) == .05


def test_singleflight_scanner():
    assert '_scanner_refresh_lock = threading.Lock()' in SOURCE
    assert 'with _scanner_refresh_lock:' in SOURCE
    assert "pair_key = (p.get('chainId'), a.lower())" in SOURCE
    assert "key = (_chain, a.lower())" in SOURCE
    assert 'return _refresh_scanner_cached()' in SOURCE


def test_two_concurrent_auto_buys_only_one_order():
    d, buys, _ = make_dashboard('base')
    entered = threading.Event()
    release = threading.Event()
    def buy(*args, **kwargs):
        buys.append(args)
        entered.set()
        assert release.wait(3)
        return {'pending': True}
    d._evm_buy_flow = buy
    multichain_auto_bot.install(d)
    def scan():
        return d._bot_scan_evm_entry(7, 'wallet', {}, 'base', 'encrypted',
                                     10., frozenset(), 5., None,
                                     True, 'test')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(scan)
        assert entered.wait(3), 'first BUY did not enter flow'
        second = executor.submit(scan)
        assert second.result(timeout=3) is False
        release.set()
        assert first.result(timeout=3) is True
    assert len(buys) == 1, 'two overlapping loops double-purchased'



def test_native_funded_concurrent_scan_only_once():
    d, buys, old = make_dashboard('base')
    d.get_evm_native_balance = lambda addr, chain: .01
    entered, release = threading.Event(), threading.Event()
    def legacy(*args, **kwargs):
        old.append(args)
        entered.set()
        assert release.wait(3)
        return True
    d._bot_scan_evm_entry = legacy
    multichain_auto_bot.install(d)
    def scan():
        return d._bot_scan_evm_entry(7, 'wallet', {}, 'base', 'encrypted',
                                     10., frozenset(), 5., None,
                                     True, 'test')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(scan)
        assert entered.wait(3)
        second = executor.submit(scan)
        assert second.result(timeout=3) is False
        release.set()
        assert first.result(timeout=3) is True
    assert len(old) == 1, 'native-funded overlapping loops double-purchased'


if __name__ == '__main__':
    test_personal_tp_sl()
    test_singleflight_scanner()
    test_two_concurrent_auto_buys_only_one_order()
    test_native_funded_concurrent_scan_only_once()
    print('PASS shared scanner, personal TP/SL and both atomic order paths')
