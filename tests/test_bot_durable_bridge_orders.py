"""Offline exactness tests for multichain bot order locks and pending bridges.

Temporary SQLite only. No production wallet/DB, quote, bridge or transfer.
Run: ./venv/bin/python tests/test_bot_durable_bridge_orders.py
"""
import sqlite3
from test_multichain_auto_bot_gasless import make_dashboard
import multichain_auto_bot as patch


def scan(d,wallet='wallet',chain='base'):
    return d._bot_scan_evm_entry(7,wallet,{},chain,'encrypted',10.0,
                                 frozenset(),5.0,None,True,'test')


def add_bridge(d,wallet='wallet',chain='base',state='pending'):
    with sqlite3.connect(d.DB_FILE) as conn:
        return conn.execute('INSERT INTO bridge_transactions '
            '(wallet,dest_chain,auto_buy_status) VALUES (?,?,?)',
            (wallet,chain,state)).lastrowid


def change_bridge(d,bridge_id,state):
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('UPDATE bridge_transactions SET auto_buy_status=? WHERE id=?',
                     (state,bridge_id))


def test_pending_true_ok_true_is_not_completed_and_releases_on_settlement():
    d,buys,_=make_dashboard('base')
    clock=[1800000000.]
    d.time.time=lambda:clock[0]
    def enqueue(wallet,data,chain,wallet_label='EVM'):
        buys.append(data)
        add_bridge(d,wallet,chain,'pending')
        return {'ok':True,'pending':True,'bridge_id':1}
    d._evm_buy_flow=enqueue
    patch.install(d)
    assert scan(d) is True and len(buys)==1
    clock[0]+=1901    # past all in-memory locks
    assert scan(d) is False and len(buys)==1
    print('PASS ok:true pending:true is an in-flight bridge, still blocked after 30-minute TTL')
    # Simulate process restart: all Python dicts/locks reset, same on-disk DB.
    d2,more,_=make_dashboard('base')
    d2.DB_FILE=d.DB_FILE
    patch.install(d2)
    assert scan(d2) is False and not more
    print('PASS gunicorn restart does not authorize another buy while persisted bridge pending')
    change_bridge(d,1,'processing')
    assert scan(d) is False and scan(d2) is False
    print('PASS processing bridge+buy remains blocked on same destination chain')
    change_bridge(d,1,'done')
    clock[0]=1800000010.  # original 30-minute memory cooldown is STILL active
    d._evm_buy_flow=lambda *a,**k:(buys.append(a) or {'ok':True})
    assert scan(d) is True and len(buys)==2
    print('PASS completed bridge releases its memory reservation promptly; no 30-minute idle wait')
    d._test_db_dir.cleanup();d2._test_db_dir.cleanup()


def test_any_candidate_native_route_and_other_users_chains():
    d,buys,original=make_dashboard('base')
    d.get_evm_native_balance=lambda *args:0.01
    patch.install(d)
    first=add_bridge(d,chain='base',state='pending')
    assert scan(d) is False and not original
    change_bridge(d,first,'processing')
    assert scan(d) is False and not original
    change_bridge(d,first,'done')
    assert scan(d) is False and len(original)==1  # mature scanner returns False
    print('PASS native-gas scanner also respects pending/processing bridge before any BUY')
    d._test_db_dir.cleanup()
    d2,buys2,_=make_dashboard('base')
    patch.install(d2)
    add_bridge(d2,chain='base',state='pending',wallet='wallet')
    # Another user does not inherit this wallet's pending bridge.
    assert scan(d2,'another-wallet') is True and len(buys2)==1
    d2._test_db_dir.cleanup()


def test_ambiguous_origin_result_remains_blocked_until_resolved():
    d,buys,_=make_dashboard('base')
    with sqlite3.connect(d.DB_FILE) as conn:
        conn.execute('INSERT INTO bridge_transactions (wallet,dest_chain,auto_buy_status,status) VALUES (?,?,?,?)',('wallet','base','pending','origin_tx_reverted'))
    patch.install(d)
    assert scan(d) is False and not buys
    print('PASS ambiguous origin broadcast failure stays blocked pending reconciliation')
    d._test_db_dir.cleanup()


def test_rpc_db_failure_fails_closed_for_bot():
    d,buys,old=make_dashboard('base')
    patch.install(d)
    d.DB_FILE='/this/path/does/not/exist/bot.db'
    assert scan(d) is False and not buys and not old
    print('PASS unavailable DB cannot masquerade as no pending bridge')
    d._test_db_dir.cleanup()


def test_legacy_no_false_suppression_on_other_chain():
    d,buys,_=make_dashboard('base')
    add_bridge(d,chain='bsc',state='pending')
    patch.install(d)
    assert scan(d) is True and len(buys)==1
    print('PASS bridge blocks only its owning wallet+destination chain')
    d._test_db_dir.cleanup()


if __name__=='__main__':
    test_pending_true_ok_true_is_not_completed_and_releases_on_settlement()
    test_any_candidate_native_route_and_other_users_chains()
    test_ambiguous_origin_result_remains_blocked_until_resolved()
    test_rpc_db_failure_fails_closed_for_bot()
    test_legacy_no_false_suppression_on_other_chain()
