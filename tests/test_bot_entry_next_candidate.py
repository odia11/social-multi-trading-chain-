"""The bot tries the next candidate when one fails an entry check.

A scan picks one candidate from the qualifying pool and runs it through the
last checks (mint/freeze authority, liquidity, pair age, LP lock, holders,
price impact, net edge, AI check). A candidate that failed one used to
`continue` the whole bot loop: the scan started over, the EVM chains were
skipped for that round, and the same token -- never put to rest -- could be
picked and rejected again on the next scan. The bot bought slowly.

Now a failed candidate is set aside for ENTRY_REJECT_COOLDOWN_SEC and the
next one in the pool is tried at once (up to ENTRY_PICKS_PER_SCAN per scan);
the EVM chains are scanned every round.
"""
import ast, os, sys
ROOT = os.path.join(os.path.dirname(__file__), '..')
checks = []
def check(name, cond):
    checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ') + name, flush=True)

src = open(os.path.join(ROOT, 'dashboard.py'), encoding='utf-8').read()
tree = ast.parse(src)
loop_fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'user_trader_loop')
pick_if = next(n for n in ast.walk(loop_fn) if isinstance(n, ast.If)
               and isinstance(n.test, ast.Name) and n.test.id == 'qualifying'
               and any(isinstance(c, ast.For) and isinstance(c.target, ast.Name)
                       and c.target.id in ('_pick_try',) for c in ast.walk(n))
               or isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == 'qualifying'
               and any(isinstance(c, ast.Call) and getattr(c.func, 'id', '') == '_check_mint_safety'
                       for c in ast.walk(n)))

def continues_with_loop(node, loops=()):
    out = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.Continue):
            out.append(loops[-1] if loops else None)
        elif isinstance(child, (ast.For, ast.While)):
            out += continues_with_loop(child, loops + (child,))
        elif not isinstance(child, (ast.FunctionDef, ast.Lambda)):
            out += continues_with_loop(child, loops)
    return out

conts = continues_with_loop(pick_if)
pick_loops = {id(l) for l in conts if l is not None and isinstance(l, ast.For)
              and isinstance(l.target, ast.Name) and l.target.id == '_pick_try'}
check('every rejection in the entry checks moves on to the next candidate, not out of the scan',
      len(conts) >= 8 and None not in conts and len(pick_loops) == 1
      and all(isinstance(l, ast.For) and l.target.id == '_pick_try' for l in conts))

block = ast.get_source_segment(src, pick_if)
check('a rejected candidate rests for a while instead of being re-picked every scan',
      '_entry_rejected[_rejected_pick] = time.time() + ENTRY_REJECT_COOLDOWN_SEC' in block
      and '_pool.remove(best)' in block and '_rejected_pick = bmint' in block)
check('...and the qualifying step skips a resting candidate',
      "_rej_exp = _entry_rejected.get(_t['mint'], 0)" in src and 'failed an entry check, resting' in src)
check('a candidate that passed every check (bought, or no balance) ends the search without resting',
      block.rstrip().endswith('_entry_rejected[_rejected_pick] = time.time() + ENTRY_REJECT_COOLDOWN_SEC')
      and '_rejected_pick = None\n' in block and 'break' in block)
check('limits: a few candidates per scan, a 10-minute rest',
      'ENTRY_PICKS_PER_SCAN = 5 ' in src and 'ENTRY_REJECT_COOLDOWN_SEC = 600 ' in src)

# the EVM pass runs after the Solana pass in the same round, unconditionally
body_src = ast.get_source_segment(src, loop_fn)
sol = body_src.index('# ── Pass 2: pick the single best entry ──')
evm = body_src.index('# ── Pass 2 (EVM): same idea')
check('the EVM chains are scanned every round, also when a Solana candidate was rejected',
      sol < evm and '→ checking m5:' in body_src)
raise SystemExit(0 if all(checks) else 1)
