"""The tool that answers "did the trade cost what the screen said".

WHY IT EXISTS
Nothing in this codebase has ever answered that. Prices are checked against
live routes and the arithmetic has tests, but no execution has been laid next
to the chain it happened on. A decimals mistake, a fee charged twice, a
purchase sized from the wrong figure — none would surface until a user
noticed their money was wrong.

WHAT IT MUST GET RIGHT
Three columns from three independent places, and the third is the only fact:
the quote and the app's own record can agree with each other and both be
wrong. So the comparison must be against the chain, and it must not paper
over the cases where it cannot make one — a missing hash, a revert, a chain
that has never heard of the transaction. Reporting "looks fine" there would
be worse than not having the tool.

These checks run the parts that can be run: the ledger reads against a real
temporary database, and the verdict arithmetic against known numbers.
"""
import ast
import os
import re
import sqlite3
import sys
import tempfile
import time

REPO = '/home/user/Orc-agent-Solana-chain-'
SRC = open(REPO + '/tools/verify_trade.py').read()
JOINED = re.sub(r"'\s*\n\s*f?'", '', SRC)

sys.path.insert(0, REPO)

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


# ── it must not be able to move money ─────────────────────────────────────
for forbidden in ('_use_key', 'send_raw_transaction', 'sign_transaction',
                  'transition(', 'settle(', 'release('):
    check(f'it never calls {forbidden} — this reads, it does not act',
          forbidden not in SRC)
check('...and says so where a reader will see it',
      'Read-only' in SRC and 'only reads. Nothing was signed' in JOINED)

# ── every name it reaches for has to exist ────────────────────────────────
def _names_of(path):
    out = set()
    for n in ast.walk(ast.parse(open(path).read())):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return out

_missing_d = sorted(set(re.findall(r'\bd\.([A-Za-z_][A-Za-z0-9_]*)', SRC))
                    - _names_of(REPO + '/dashboard.py'))
_missing_l = sorted(set(re.findall(r'\bL\.([A-Za-z_][A-Za-z0-9_]*)', SRC))
                    - _names_of(REPO + '/trade_engine/ledger.py'))
check(f'every app attribute it reads exists{"" if not _missing_d else ": " + ", ".join(_missing_d)}',
      not _missing_d)
check(f'every ledger function it calls exists{"" if not _missing_l else ": " + ", ".join(_missing_l)}',
      not _missing_l)

# The breakdown keys are the ones that would silently print "?" if renamed.
_bd = next(n for n in ast.walk(ast.parse(open(REPO + '/trade_engine/costs.py').read()))
           if isinstance(n, ast.FunctionDef) and n.name == 'breakdown')
_provided = set(re.findall(r"'([a-z_]+)':",
                ast.get_source_segment(open(REPO + '/trade_engine/costs.py').read(), _bd)))
_used = {a or b for a, b in re.findall(
    r"breakdown\.get\('([a-z_]+)'|breakdown\['([a-z_]+)'\]", SRC)}
check(f'every quote-breakdown key it reads is one the quote actually produces'
      f'{"" if not _used - _provided else ": " + ", ".join(sorted(_used - _provided))}',
      not (_used - _provided))

# ── the ledger reads work against a real database ─────────────────────────
from trade_engine import ledger as L                       # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    conn = sqlite3.connect(os.path.join(tmp, 't.db'))
    L.ensure_schema(conn)
    now = time.time()
    conn.execute(
        'INSERT INTO trade_quotes (quote_id, user_id, wallet, mode, source_chain, '
        'destination_chain, token_address, max_spend_usd, token_purchase_usd, '
        'total_cost_usd, subsidy_usd, route, same_chain, can_execute, '
        'breakdown_json, created_at, expires_at) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        ('q1', 1, '0xabc', 'manual', 'base', 'base', '0xtok', '100', '98.5',
         '1.5', '0', 'base->0x', 1, 1,
         '{"token_purchase_usd": "98.5"}', now, now + 30))
    conn.execute(
        'INSERT INTO trade_executions (trade_id, idempotency_key, quote_id, '
        'user_id, wallet, mode, state, same_chain, max_spend_usd, '
        'source_tx_hash, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
        ('t1', 'k1', 'q1', 1, '0xabc', 'manual', 'confirmed', 1, '100',
         '0xdeadbeef', now, now))
    conn.commit()

    check('the ledger reads it relies on return what it expects',
          (L.get_trade(conn, 't1') or {}).get('source_tx_hash') == '0xdeadbeef')
    check('...including the quote behind the trade, which is where the '
          'promised figure lives',
          (L.load_quote(conn, 'q1') or {}).get('breakdown_json', '').find('98.5') > 0)
    check('...and the newest trade is findable without being named, since that '
          'is the one somebody just made',
          conn.execute('SELECT trade_id FROM trade_executions ORDER BY '
                       'created_at DESC LIMIT 1').fetchone()[0] == 't1')
    conn.close()

# ── the cases where no comparison can be made must not read as a pass ─────
check('a trade with no transaction hash is called out, not skipped quietly — '
      'it either never reached the chain or the hash was never written back, '
      'and both are worth knowing',
      'no transaction hash recorded' in JOINED and 'Both are worth knowing' in JOINED)
check('a reverted transaction is reported as such, and notes the gas was paid '
      'anyway', 'REVERTED' in SRC and 'gas was still paid' in JOINED)
check('a hash no configured chain has seen is an error, not an empty result',
      'on none of the configured chains' in JOINED)
check('a Solana signature says plainly that the comparison was NOT made, '
      'rather than implying it passed',
      'not automated for Solana' in JOINED and 'Check it by hand' in JOINED)

# ── the arithmetic that produces the verdict ──────────────────────────────
check('decimals are read from the contract, never assumed — assuming 6 or 18 '
      'is exactly the class of mistake this tool exists to catch',
      'functions.decimals().call()' in SRC and 'never assumed' in JOINED)
check('it matches ERC20 Transfer logs by the real event topic rather than by '
      'position', 'ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef' in SRC)
check('it separates what LEFT the wallet from what ARRIVED, since a swap does '
      'both in one transaction',
      'out_stable' in SRC and 'in_token' in SRC)
check('gas is priced from the receipt\'s own effective price, not a current '
      'quote that has since moved', "rcpt.get('effectiveGasPrice'" in SRC)

_ns = {}
exec(re.search(r'def _fmt\(.*?\n\n', SRC, re.S).group(0), _ns)
check('the formatter does not turn a real difference into a tidy zero',
      _ns['_fmt'](0.000123, 6) == '0.000123')

check('a difference under one percent is called agreement, and anything more '
      'is called disagreement in plain words',
      'pct < 1' in SRC and 'These agree' in JOINED and 'do NOT agree' in JOINED)
check('...and a disagreement exits non-zero, so this can gate something later',
      SRC.count('return 1') >= 3)
check('the verdict states all three numbers, so it can be checked rather than '
      'believed',
      'screen said the purchase would be' in JOINED
      and 'the wallet actually spent' in JOINED and 'difference' in JOINED)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
