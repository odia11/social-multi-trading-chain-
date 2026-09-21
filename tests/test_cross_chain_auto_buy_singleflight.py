"""Regression coverage for cross-chain auto-buy single-flight behavior."""
import ast
import concurrent.futures
import sqlite3
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / 'dashboard.py').read_text()
MOD = ast.parse(SRC)
NAMES = {
    '_get_auto_bridge_buy_lock',
    '_active_auto_buy_bridge',
    '_maybe_start_auto_bridge_for_buy',
}
NODES = [n for n in MOD.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]


def namespace():
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    db = tmp.name
    conn = sqlite3.connect(db)
    conn.execute('''CREATE TABLE bridge_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, source_chain TEXT, dest_chain TEXT,
        token_in TEXT, token_out TEXT, amount_in REAL,
        provider TEXT DEFAULT '0x', status TEXT,
        initiated_by TEXT, auto_buy_token_address TEXT,
        auto_buy_requested_usdc REAL, auto_buy_status TEXT
    )''')
    conn.commit(); conn.close()

    calls = []
    ns = {
        'threading': threading,
        'sqlite3': sqlite3,
        'DB_FILE': db,
        '_AUTO_BRIDGE_BUFFER_PCT': 0.05,
        '_auto_bridge_buy_locks': {},
        '_auto_bridge_buy_locks_guard': threading.Lock(),
        'EVM_CHAINS': {'base': {'usdc': '0xUSDC'}},
        'user_currency_label': lambda c: 'USDC',
        '_find_bridge_source_chain': lambda *a: ('solana', 'SOLUSDC', 100.0),
    }

    def bridge(user_id, wallet, source_chain, dest_chain, source_token, dest_token,
               amount, initiated_by='user', auto_buy_token_address=None,
               auto_buy_requested_usdc=None):
        calls.append((user_id, dest_chain, auto_buy_token_address))
        conn = sqlite3.connect(db)
        cur = conn.execute('''INSERT INTO bridge_transactions
            (user_id,source_chain,dest_chain,token_in,token_out,amount_in,
             provider,status,initiated_by,auto_buy_token_address,
             auto_buy_requested_usdc,auto_buy_status)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
             (user_id, source_chain, dest_chain, source_token, dest_token, amount,
              '0x', 'origin_tx_pending', initiated_by, auto_buy_token_address,
              auto_buy_requested_usdc, 'pending'))
        conn.commit(); rid = cur.lastrowid; conn.close()
        return True, '0xtx', rid
    ns['_execute_cross_chain_bridge'] = bridge
    exec(compile(ast.Module(body=NODES, type_ignores=[]), '<bridge>', 'exec'), ns)
    return ns, calls, db


def test_two_concurrent_requests_create_one_bridge():
    ns, calls, db = namespace()
    f = ns['_maybe_start_auto_bridge_for_buy']
    def run():
        return f(7, 'wallet', '0xevm', 'base', '0xTOKEN', 10.0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        a, b = ex.submit(run), ex.submit(run)
        ra, rb = a.result(), b.result()
    assert len(calls) == 1, calls
    assert ra['bridge_id'] == rb['bridge_id']
    assert {ra['reused'], rb['reused']} == {False, True}


def test_retry_reuses_live_bridge_even_after_time_window():
    ns, calls, db = namespace()
    f = ns['_maybe_start_auto_bridge_for_buy']
    first = f(7, 'wallet', '0xevm', 'base', '0xTOKEN', 10.0)
    second = f(7, 'wallet', '0xevm', 'base', '0xTOKEN', 10.0)
    assert len(calls) == 1
    assert second['reused'] is True
    assert second['bridge_id'] == first['bridge_id']


def test_terminal_failure_closes_attached_buy_state_in_source():
    assert "auto_buy_status='failed'" in SRC
    assert "Funding bridge did not complete" in SRC
    assert "Funding bridge timed out before purchase" in SRC


def test_evm_origin_bridge_uses_user_funded_gasless_setup_before_sponsor():
    block = SRC[SRC.index("if _origin_native is not None and _origin_native <= 0:"):
                SRC.index("if dest_chain == 'solana':")]
    assert "globals().get('_gasless_evm_native_topup')" in block
    assert block.index('_gasless_topup(private_key, origin_chain)') < block.index('_sponsor_evm_gas(')


if __name__ == '__main__':
    for name in sorted(n for n in globals() if n.startswith('test_')):
        globals()[name]()
        print('PASS', name)
    print('ALL CROSS-CHAIN AUTO-BUY REGRESSIONS PASSED')
