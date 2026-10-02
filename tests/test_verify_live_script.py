"""Static contract for the read-only Solana-only live verifier."""
import ast, os, sys
REPO=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT=open(REPO+'/tools/verify_live.py').read()
APP=open(REPO+'/dashboard.py').read()
tree=ast.parse(SCRIPT); app_tree=ast.parse(APP)
checks=[]
def check(name,cond): checks.append(bool(cond)); print(('PASS ' if cond else 'FAIL ')+name)

defined=set()
for n in ast.walk(app_tree):
    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): defined.add(n.name)
    elif isinstance(n,ast.Assign):
        defined.update(t.id for t in n.targets if isinstance(t,ast.Name))
    elif isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name): defined.add(n.target.id)
    elif isinstance(n,ast.Import):
        defined.update((a.asname or a.name.split('.')[0]) for a in n.names)
    elif isinstance(n,ast.ImportFrom):
        defined.update((a.asname or a.name) for a in n.names)
used=sorted({n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)
             and isinstance(n.value,ast.Name) and n.value.id=='d'})
check('every dashboard name used by verifier exists',not [u for u in used if u not in defined])
check('verifier has no 0x dependency',
      'ZEROX_API_KEY' not in SCRIPT and 'api.0x.org' not in SCRIPT
      and 'ACTIVE_EVM_CHAINS' not in SCRIPT and 'bsc_wallet_address' not in SCRIPT)
check('verifier checks Solana price feed','_dex_get' in SCRIPT and 'SOL price feed' in SCRIPT)
check('verifier checks Jupiter quote','_jupiter_quote' in SCRIPT and 'Jupiter quote' in SCRIPT)
check('verifier checks DexScreener','DexScreener' in SCRIPT)
check('verifier states active product chain is Solana only',
      "report(OK, 'active trading chain', 'Solana via Jupiter; legacy non-Solana routes are disabled')" in SCRIPT)
called={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
forbidden={'_execute_evm_swap','_execute_user_swap','_execute_user_swap_ex','execute_trade',
           '_charge_txn_fee','_sponsor_evm_gas','_sponsor_solana_gas',
           '_evm_buy_flow','_evm_sell_flow','_solana_buy_flow'}
check('verifier never trades, charges or sponsors',not (called & forbidden))
check('verifier never decrypts keys','decrypt_private_key' not in SCRIPT and '_use_key' not in SCRIPT)
check('verifier identifies itself as read-only','READ-ONLY' in SCRIPT)
check('one failed check does not abort remaining checks',
      'def attempt(' in SCRIPT and 'except Exception as e:' in SCRIPT)
check('summary returns nonzero for essential failures','return 1 if failed else 0' in SCRIPT)
check('summary repeats failure reason','failed = [(n, d)' in SCRIPT and 'def _why(' in SCRIPT)
check('app itself no longer defines ZEROX key',
      "os.environ.get('ZEROX_API_KEY'" not in APP and 'ZEROX_API_KEY    =' not in APP)
print(f'\n{sum(checks)}/{len(checks)} checks passed')
raise SystemExit(0 if all(checks) else 1)
