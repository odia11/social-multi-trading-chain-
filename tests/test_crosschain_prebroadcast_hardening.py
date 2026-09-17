import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import crosschain_prebroadcast_hardening as H


def check(name, ok):
    print(('PASS ' if ok else 'FAIL ') + name)
    if not ok:
        raise AssertionError(name)


with tempfile.TemporaryDirectory() as td:
    db = str(Path(td) / 'test.db')
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE trade_executions (trade_id TEXT PRIMARY KEY, wallet TEXT, state TEXT, created_at REAL)')
    conn.execute('''CREATE TABLE trade_crosschain (
        trade_id TEXT PRIMARY KEY, source_chain TEXT, source_amount_raw TEXT,
        provider_quote_id TEXT, source_tx_hash TEXT DEFAULT '',
        source_sent_at REAL DEFAULT 0, provider_status TEXT DEFAULT '', updated_at REAL DEFAULT 0
    )''')
    conn.execute("INSERT INTO trade_executions VALUES ('t1','wallet1','AWAITING_SOURCE',1)")
    conn.execute("INSERT INTO trade_crosschain (trade_id,source_chain,source_amount_raw,provider_quote_id) VALUES ('t1','base','30000000','q-provider')")
    conn.commit(); conn.close()

    fake_d = SimpleNamespace(DB_FILE=db, te_ledger=SimpleNamespace(AWAITING_SOURCE='AWAITING_SOURCE'))
    H._ctx.wallet = 'wallet1'
    H._ctx.source_chain = 'base'
    H._ctx.route = SimpleNamespace(source_amount_raw=30000000, quote_id='q-provider')
    H._persist_prebroadcast_hash(fake_d, '0xabc123')

    conn = sqlite3.connect(db)
    row = conn.execute('SELECT source_tx_hash,source_sent_at,provider_status FROM trade_crosschain WHERE trade_id="t1"').fetchone()
    conn.close()
    check('signed transaction identity is persisted before broadcast', row[0] == '0xabc123')
    check('pre-broadcast persistence records a timestamp', float(row[1]) > 0)
    check('prepared state is explicit for recovery/support', row[2] == 'origin_tx_prepared')

    try:
        H._persist_prebroadcast_hash(fake_d, '0xsecond')
    except RuntimeError:
        duplicate_refused = True
    else:
        duplicate_refused = False
    check('a second pre-broadcast claim for the same leg is refused', duplicate_refused)


class FakeStatus:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def broken_status(*args, **kwargs):
    raise TimeoutError('provider unavailable')


fake_install = SimpleNamespace(
    _te_cc_source_sender=lambda *a, **k: (lambda route: None),
    _te_cc_status_fetcher=broken_status,
    te_crosschain=SimpleNamespace(UNKNOWN='unknown', CrossChainStatus=FakeStatus),
)
H.install(fake_install)
status = fake_install._te_cc_status_fetcher('base', '0xabc', 'q1')
check('provider status outages become UNKNOWN instead of aborting recovery',
      status.status == 'unknown' and not status.filled and not status.failed)
check('status-outage reason remains available for diagnostics',
      'TimeoutError' in status.failure_reason)

app_entry = (ROOT / 'app_entry.py').read_text()
check('production entrypoint installs pre-broadcast hardening',
      '_install_crosschain_prebroadcast_hardening(_dashboard)' in app_entry)
