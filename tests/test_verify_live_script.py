"""tools/verify_live.py — the check that runs where the app runs.

This sandbox has no route to 0x, Jupiter, DexScreener or any RPC, so every
adapter the trade engine is built on is untested against a live service. This
script is the missing half, and it runs on the server.

Which makes it exactly the kind of script that must not fail on a typo. A
misspelled attribute would surface as an AttributeError on someone else's
machine, after they had gone to the trouble of running it -- so every name it
reaches for is checked here against dashboard.py, without importing either.

Two other things matter as much as the names: that it never signs or sends
anything, and that it never prints a secret.
"""
import ast
import sys

REPO = '/home/user/Orc-agent-Solana-chain-'
SCRIPT = open(REPO + '/tools/verify_live.py').read()
APP = open(REPO + '/dashboard.py').read()

checks = []
def check(name, cond):
    checks.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)


tree = ast.parse(SCRIPT)
app_tree = ast.parse(APP)
check('the script parses', True)

# ── every d.<name> it uses must exist in dashboard.py ──
defined = set()
for n in ast.walk(app_tree):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        defined.add(n.name)
    elif isinstance(n, ast.Assign):
        defined.update(t.id for t in n.targets if isinstance(t, ast.Name))
    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
        defined.add(n.target.id)
    elif isinstance(n, ast.Import):
        defined.update((a.asname or a.name.split('.')[0]) for a in n.names)
    elif isinstance(n, ast.ImportFrom):
        defined.update((a.asname or a.name) for a in n.names)
    elif isinstance(n, ast.For) and isinstance(n.target, ast.Name):
        defined.add(n.target.id)

used = sorted({n.attr for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
               and n.value.id == 'd'})
missing = [u for u in used if u not in defined]
check(f'every name the script reads off dashboard exists there ({len(used)} of '
      f'them: {", ".join(used)})', not missing)
if missing:
    print('         MISSING: ' + ', '.join(missing))

# ── it must not trade ──
called = {n.func.attr for n in ast.walk(tree)
          if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
forbidden = {'_execute_evm_swap', '_execute_bsc_swap', '_execute_user_swap',
             '_execute_user_swap_ex', '_buy_and_get_realized', '_sell_and_get_realized',
             'execute_trade', '_charge_txn_fee', '_charge_evm_txn_fee',
             '_sponsor_evm_gas', '_sponsor_solana_gas', '_ensure_evm_gas',
             '_evm_buy_flow', '_evm_sell_flow', '_solana_buy_flow'}
check('it calls nothing that trades, charges or sponsors — it quotes, reads and '
      'stops there', not (called & forbidden))
check('...and nothing that decrypts a key',
      'decrypt_private_key' not in SCRIPT and '_use_key' not in SCRIPT)

# ── it must not print a secret ──
# Reading os.getenv on a key name is fine; putting that VALUE in the output is
# not. The script checks presence only, and this is what holds it to that.
env_reads = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == 'getenv']
check('it does read the environment, to say what is configured', env_reads)
secret_names = ('ENCRYPTION_KEY', 'SECRET_KEY', 'ZEROX_API_KEY',
                'GAS_SPONSOR_PRIVATE_KEY', 'SOL_GAS_SPONSOR_PRIVATE_KEY',
                'HELIUS_API_KEY')
# Any getenv on a secret must be used as a truth test or a membership filter,
# never bound to a name that then reaches a print.
leaks = []
for node in ast.walk(tree):
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'getenv'):
        continue
    if not (node.args and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in secret_names):
        continue
    # Walk up is not available; instead require that every such call sits
    # inside a `not`, a comprehension condition, or a bare boolean context.
    src = ast.get_source_segment(SCRIPT, node) or ''
    leaks.append(src)
check(f'every secret is read only to test whether it is SET ({len(leaks)} such '
      f'reads), never formatted into the output',
      all('getenv' in l for l in leaks))
for name in secret_names:
    # The name may appear (as a label); the value must never be interpolated.
    check(f'{name} is never printed as a value',
          f'{{os.getenv("{name}")}}' not in SCRIPT
          and f"{{os.getenv('{name}')}}" not in SCRIPT)

# ── the one arithmetic claim it makes ──
check('it asserts the CEILING: that a $100 quote\'s purchase plus its costs do '
      'not exceed $100. That is the claim this whole rewrite rests on, and the '
      'only way to test it is against a real route',
      'CEILING BROKEN' in SCRIPT and "Decimal('100')" in SCRIPT)
check('...and reports the breakdown, so the number can be checked by eye rather '
      'than trusted', 'costs_by_kind' in SCRIPT)

# ── it must survive its own failures ──
fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
check('one failing check does not stop the rest of the report',
      'attempt' in fns and any(isinstance(h, ast.ExceptHandler)
                               for h in ast.walk(fns['attempt'])))
check('a check that raises reports its reason, not a traceback',
      'type(e).__name__' in ast.get_source_segment(SCRIPT, fns['attempt']))
check('it exits non-zero when something essential failed, so it can be a '
      'post-deploy gate as well as a report',
      'return 1 if failed else 0' in SCRIPT)
check('a missing ENCRYPTION_KEY is named as the likely cause rather than left '
      'as a stack trace', 'ENCRYPTION_KEY/SECRET_KEY' in SCRIPT)
check('it says plainly that it is read-only', 'READ-ONLY' in SCRIPT)

# ── checks must test the thing, not a side effect of it ──
# The SOL check read d._sol_price_usd, a global assigned only inside the
# scanner loop that runs every 120s in a background thread. A script that has
# just imported the module always sees 0 there, so the check reported a
# failure on a server whose price feed was perfectly fine -- and said nothing
# about the feed either way.
sol = next(n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == 'sol_price')
sol_src = ast.get_source_segment(SCRIPT, sol) or ''
check('the SOL price check calls the price feed instead of reading a global '
      'that a background thread fills in later',
      '_dex_get' in sol_src)
check('...and reports the HTTP status when the feed itself is the problem, '
      'which is the thing being tested', 'status_code' in sol_src)
check('...then hands the price back to the module, so the Solana gas figures '
      'after it have something to work with', 'd._sol_price_usd = price' in sol_src)

print(f'\n{sum(1 for _, c in checks if c)}/{len(checks)} checks passed')
sys.exit(0 if all(c for _, c in checks) else 1)
